import unittest

from mail_search.application.passages import find_passage, query_terms


class PassageTests(unittest.TestCase):
    def test_best_body_passage_uses_original_spelling_and_utf16_offsets(self):
        doc = "Тема: Щетка\n" + "Описание. " * 30 + "📦 Для заказа: щетку для снега."
        passage = find_passage(doc, query_terms("покажи щётка для снега"))
        self.assertGreater(passage["offset"], 200)
        raw = doc.encode("utf-16-le")
        start = passage["offset"] * 2
        excerpt = passage["text"].encode("utf-16-le")
        self.assertEqual(raw[start:start + len(excerpt)], excerpt)
        self.assertEqual([excerpt[2*a:2*b].decode("utf-16-le") for a, b in passage["ranges"]],
                         ["щетку", "снега"])

    def test_no_highlight_without_a_term_and_header_without_label(self):
        self.assertIsNone(find_passage("От: Анна", query_terms("найди остаток")))
        self.assertIsNone(find_passage("Тема: Новость", set()))
        hit = find_passage("Тема: Отчёт по работе\nТекст письма: Готово.", query_terms("отчет"))
        self.assertEqual(hit["text"], "Отчёт по работе")
