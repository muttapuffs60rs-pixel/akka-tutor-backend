import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from image_understanding import understand_image, ordered_text
import test_chat_cost_controls as chat_tests


IMAGE_BYTES = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00(\x00\x00\x00(\x08\x02\x00\x00\x00\x03\x9c/:\x00\x00\x00LIDATx\x9c\xed\xcd\xb1\x01\xc00\x0c\xc30\x87\xff\xff\xec\xae\xd1\x03\xccP\xe1\x01\x9c\xdd\x9d\x17x\xb2Nc\x11fvk\xac\xc1\xabRc\r^\x95\x1ak\xf0\xaa\xd4X\x83W\xa5\xc6\x1a\xbc*5\xd6\xe0U\xa9\xb1\x06\xafJ\x8d5x\xd5\xfc<\xfe\x00\x83\xeb\x03M\x08\x99x\x08\x00\x00\x00\x00IEND\xaeB`\x82'

QUESTION = ('AB and CD are parallel chords of a circle with centre O. '
            'AB = 8 cm and CD = 6 cm. OM is perpendicular to AB and '
            'OL is perpendicular to CD. LM = 7 cm. Find the radius.')


class ImageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine_patch = patch('image_understanding.tesseract_path', return_value=None)
        self.engine_patch.start()
        self.addCleanup(self.engine_patch.stop)

    def test_shuffled_words_restore_reading_order_and_flag_uncertainty(self):
        def box(x, y, text, score=.99):
            return ([[x,y],[x+20,y],[x+20,y+10],[x,y+10]],text,score)
        text, uncertain = ordered_text([box(60,0,'O.'),box(0,20,'AB = 8cm'),
            box(0,0,'with'),box(25,0,'centre'),box(80,20,'CD = 6cm',.4)])
        self.assertEqual(text, 'with centre O.\nAB = 8cm CD = 6cm')
        self.assertEqual(uncertain, ['CD = 6cm'])

    async def test_independent_reading_preserves_number_disagreement(self):
        reader = Mock()
        reader.readtext.return_value = ['AB = 8 cm']
        with patch('image_understanding.tesseract_path', return_value='tesseract'), patch(
                'image_understanding.subprocess.run', return_value=SimpleNamespace(
                    returncode=0, stdout=b'AB = 3 cm')):
            text = await understand_image(IMAGE_BYTES, reader)
        self.assertIn('AB = 8 cm',text)
        self.assertIn('AB = 3 cm',text)
        self.assertIn('Never silently resolve conflicting numbers',text)

    async def test_mostly_uncertain_text_requests_a_better_photo(self):
        reader = Mock()
        reader.readtext.return_value = [
            ([[0,y],[20,y],[20,y+10],[0,y+10]], 'blurry words', .3)
            for y in (0,20,40,60)]
        with self.assertRaises(HTTPException) as error:
            await understand_image(IMAGE_BYTES,reader)
        self.assertEqual(error.exception.status_code,422)
        self.assertIn('sharper photo',error.exception.detail)

    async def test_geometry_and_short_questions_use_local_ocr(self):
        for lines in ([QUESTION], ['x = 3'], ['  First line ', 'Second line']):
            reader = Mock()
            reader.readtext.return_value = lines
            text = await understand_image(IMAGE_BYTES, reader)
            self.assertTrue(text.startswith('\n'.join(line.strip() for line in lines)))
            self.assertEqual(reader.readtext.call_args.kwargs, {'detail': 1, 'paragraph': False})

    async def test_ocr_failure_returns_actionable_error(self):
        reader = Mock()
        reader.readtext.side_effect = ValueError('Cannot decode')
        with self.assertRaises(HTTPException) as error:
            await understand_image(IMAGE_BYTES, reader)
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(error.exception.headers['X-Chat-Error'], 'image_unavailable')

    async def test_unreadable_images_do_not_reach_tutor(self):
        for lines in (None, [], ['   '], ['---', '...']):
            reader = Mock()
            reader.readtext.return_value = lines
            with self.assertRaises(HTTPException) as error:
                await understand_image(IMAGE_BYTES, reader)
            self.assertEqual(error.exception.status_code, 422)
            self.assertIn('clearer photo', error.exception.detail)

    async def test_ocr_timeout_is_bounded(self):
        class SlowReader:
            def readtext(self, *args, **kwargs):
                import time
                time.sleep(.04)
                return ['Late text']
        with patch('image_understanding.OCR_TIMEOUT', .001):
            with self.assertRaises(HTTPException) as error:
                await understand_image(IMAGE_BYTES, SlowReader())
        self.assertEqual(error.exception.status_code, 503)


class ImageRouteTests(unittest.IsolatedAsyncioTestCase):
    setUp = chat_tests.ChatCostTests.setUp

    async def test_image_and_question_reach_answer_stream(self):
        self.request.subject = 'Maths'
        self.request.grade_level = 9
        self.request.question = 'Solve this question'
        self.request.image_url = 'https://example.test/image.png'
        self.env['download_chat_image'] = Mock(return_value=(IMAGE_BYTES, 'image/png'))
        self.env['ocr_reader'] = Mock()
        self.env['ocr_reader'].readtext.return_value = [QUESTION]
        engine_patch = patch('image_understanding.tesseract_path', return_value=None)
        engine_patch.start()
        self.addCleanup(engine_patch.stop)
        async def stream(messages):
            self.assertIn(QUESTION, messages[-1].content)
            self.assertIn('Solve this question', messages[-1].content)
            self.assertIn('rather than guess', messages[-1].content)
            yield SimpleNamespace(content='The radius is 5 cm.', usage_metadata={'input_tokens': 10, 'output_tokens': 8})
        model = Mock()
        model.bind.return_value.astream = stream
        self.env['deepseek_llm'] = model
        response = await self.env['chat_handler'](self.request, 'student')
        self.assertEqual(''.join([chunk async for chunk in response.body_iterator]), 'The radius is 5 cm.')

        record = [call.args[1]['record'] for call in self.db.rpc.call_args_list
                  if call.args[0] == 'finish_learning_credit_request'][-1]
        self.assertEqual(record['vision_input_tokens'], 0)
        self.assertEqual(record['vision_output_tokens'], 0)
