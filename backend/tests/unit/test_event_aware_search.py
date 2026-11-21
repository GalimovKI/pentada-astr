from datetime import date
from unittest import TestCase

from mail_search.domain.models import Document, SearchRequest
from mail_search.search.event_aware import create_engine, prospective_only


class EventAwareSearchTests(TestCase):
    def test_modal_scope_and_independent_assertion(self):
        self.assertEqual(prospective_only("Таможня дала разрешение клиента на погрузку."), {"погрузк"})
        self.assertEqual(prospective_only("Выдано разрешение на погрузку. Контейнер погружен."), set())
        self.assertEqual(prospective_only("Разрешение получено. На погрузку ушло 10 минут."), set())

    def test_permission_queries_and_undated_branch_keep_lexical_order(self):
        day = date(2028, 4, 5)
        documents = (
            Document("a", "box", "Тема: План запуска\nВыдано разрешение на запуск.", day),
            Document("b", "box", "Тема: Запуск сервера\nСервер запущен.", day),
        )
        engine = create_engine(documents, {"prospective_penalty": 0.55})
        for query in ("запуск сервера", "разрешение на запуск вчера"):
            request = SearchRequest(query, "box", date(2028, 4, 6))
            with self.subTest(query=query):
                self.assertEqual(engine.search(request, 10), engine.baseline.search(request, 10))

    def test_status_reorders_only_top_prefix_and_keeps_day_and_mailbox(self):
        received = date(2028, 4, 5)
        documents = (
            Document("a", "box", "Разрешение таможни на погрузку контейнера.", received),
            Document("b", "box", "Контейнер погружен.", received),
            Document("c", "box", "Сводка по зарплатам.", received),
            Document("d", "box-foreign", "Контейнер погружен.", received),
            Document("e", "box", "Контейнер погружен.", date(2028, 4, 7)),
        )
        engine = create_engine(documents, {"prospective_penalty": 0.55, "rerank_depth": 2})
        request = SearchRequest("погрузка контейнера вчера", "box", date(2028, 4, 6))
        self.assertEqual([hit.doc_id for hit in engine.baseline.search(request, 10)], ["a", "b", "c"])
        self.assertEqual([hit.doc_id for hit in engine.search(request, 10)], ["b", "a", "c"])
        self.assertEqual([hit.doc_id for hit in engine.search(request, 1)], ["b"])
