import unittest
from chat_cost_controls import retrieval_query


class RetrievalQueryTests(unittest.TestCase):
    def test_new_topic_does_not_inherit_old_topic(self):
        history = [{'role': 'user', 'content': 'What is photosynthesis?'}]
        question = 'What is the difference between solids, liquids and gases?'
        self.assertEqual(retrieval_query(question, history), question)
        self.assertEqual(retrieval_query('What is friction?', history), 'What is friction?')

    def test_referential_followup_keeps_topic(self):
        history = [{'role': 'user', 'content': 'What is photosynthesis?'},
                   {'role': 'assistant', 'content': 'Plants make food.'}]
        self.assertEqual(retrieval_query('Why is it important?', history),
                         'What is photosynthesis? Why is it important?')
        self.assertEqual(retrieval_query('Give an example', history),
                         'What is photosynthesis? Give an example')

    def test_empty_history(self):
        self.assertEqual(retrieval_query('Explain this', []), 'Explain this')
