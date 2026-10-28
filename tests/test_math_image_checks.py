import csv
import io
import unittest

import cv2
import numpy as np
from PIL import Image

from math_image_checks import perpendicular_glyphs, corrected_tesseract, verified_chord_check


def problem(a=8, b=6, d=7, first='AB', second='CD', feet='LM'):
    return (f'{first} and {second} are parallel chords of a circle with centre O. '
            f'{first} = {a} cm and {second} = {b} cm. '
            f'OM ⊥ {first} and OL ⊥ {second}, distance between {feet} is {d} cm. Find the radius.')


class GlyphTests(unittest.TestCase):
    def image(self, kind):
        image = np.full((100, 100, 3), 255, np.uint8)
        if kind == 'perpendicular':
            cv2.line(image, (50,25), (50,65), (0,0,0), 3)
            cv2.line(image, (30,65), (70,65), (0,0,0), 3)
        elif kind == 'L':
            cv2.line(image, (30,25), (30,65), (0,0,0), 3)
            cv2.line(image, (30,65), (70,65), (0,0,0), 3)
        elif kind == 'plus':
            cv2.line(image, (50,25), (50,65), (0,0,0), 3)
            cv2.line(image, (30,45), (70,45), (0,0,0), 3)
        elif kind == 'one':
            cv2.line(image, (50,25), (50,65), (0,0,0), 3)
            cv2.line(image, (30,65), (70,65), (0,0,0), 3)
            cv2.line(image, (38,35), (50,25), (0,0,0), 3)
        elif kind == 'I':
            cv2.line(image, (50,25), (50,65), (0,0,0), 3)
            for y in (25,65):
                cv2.line(image, (30,y), (70,y), (0,0,0), 3)
        return Image.fromarray(image)

    def test_perpendicular_is_detected_from_pixels(self):
        self.assertEqual(len(perpendicular_glyphs(self.image('perpendicular'))), 1)

    def test_similar_characters_are_not_perpendiculars(self):
        for kind in ('L','plus','one','I','blank'):
            with self.subTest(kind=kind):
                self.assertEqual(perpendicular_glyphs(self.image(kind)), [])

    def test_word_correction_requires_overlapping_verified_pixels(self):
        buffer = io.StringIO()
        fields = ['level','page_num','block_num','par_num','line_num','left','top','width','height','conf','text']
        writer=csv.DictWriter(buffer,fieldnames=fields,delimiter='\t');writer.writeheader()
        writer.writerow(dict(zip(fields,[5,1,1,1,1,10,20,100,40,80,'OM+'])))
        writer.writerow(dict(zip(fields,[5,1,1,1,1,120,20,30,40,80,'AB'])))
        raw=buffer.getvalue()
        self.assertEqual(corrected_tesseract(raw,[])[0], 'OM+ AB')
        text, repairs = corrected_tesseract(raw,[(80,25,25,30)])
        self.assertEqual(text,'OM⊥ AB')
        self.assertEqual(len(repairs),1)

    def test_masked_symbol_is_restored_between_words_on_same_line(self):
        buffer=io.StringIO()
        fields=['level','page_num','block_num','par_num','line_num','left','top','width','height','conf','text']
        writer=csv.DictWriter(buffer,fieldnames=fields,delimiter='\t');writer.writeheader()
        for values in ([5,1,1,1,1,10,20,30,40,90,'OM'],[5,1,1,1,1,80,20,30,40,90,'AB']):
            writer.writerow(dict(zip(fields,values)))
        text,repairs=corrected_tesseract(buffer.getvalue(),[(45,25,25,30)])
        self.assertEqual(text,'OM ⊥ AB')
        self.assertEqual(len(repairs),1)


class ChordTests(unittest.TestCase):
    def test_opposite_side_question_needs_no_diagram_clarification(self):
        check = verified_chord_check(problem(),problem())
        self.assertIn('radius=5 cm',check)
        self.assertIn('opposite sides',check)

    def test_other_measurements_and_same_side_case_are_solved(self):
        for a,b,d,radius,arrangement in [(8,6,1,5,'same side'), (6,6,8,5,'opposite sides'),
                (12,16,14,10,'opposite sides'), (8,6,7,5,'opposite sides')]:
            with self.subTest(a=a,b=b,d=d):
                check=verified_chord_check(problem(a,b,d),problem(a,b,d))
                self.assertIn(f'radius={radius:.10g} cm',check)
                self.assertIn(arrangement,check)

    def test_changed_labels_and_split_ocr_points_are_supported(self):
        text=problem(first='PQ',second='RS').replace('LM is','L Mis')
        self.assertIn('radius=5 cm',verified_chord_check(text,text))

    def test_conflicting_or_unproven_facts_do_not_get_a_certificate(self):
        for first,second in [(problem(),problem(3)), (problem(),problem().replace('⊥','L')),
                (problem(),problem().replace('OL ⊥ CD','ON ⊥ CD')),
                (problem(),problem().replace('CD = 6 cm','CD = 6 mm')),
                (problem(),problem().replace('7 cm','0 cm')),
                (problem(),problem()+' AB = 3 cm'),
                (problem().replace('distance between','length of'),problem())]:
            with self.subTest(second=second):
                self.assertEqual(verified_chord_check(first,second),'')
