from src.agent import tools
from src.parser import groovy_summarizer
from src.parser.groovy_summarizer import generate_groovy_summary


def test_get_resource_detail_follows_process_scoped_step_relationship(monkeypatch):
    captured = {}

    def fake_run_query(query, parameters):
        captured["query"] = query
        captured["parameters"] = parameters
        return [{
            "filename": "example.groovy",
            "kind": "groovy",
            "resolved": False,
            "purpose": None,
            "complexity": None,
            "used_in_iflows": ["example_iflow"],
        }]

    monkeypatch.setattr(tools, "run_query", fake_run_query)

    detail = tools.get_resource_detail("example.groovy")
    assert detail["resources"][0]["used_in_iflows"] == ["example_iflow"]
    assert captured["parameters"] == {"filename": "example.groovy", "artifact_id": None}
    assert "(i:IFlow)<-[:PART_OF]-(:Process)<-[:BELONGS_TO]-(:Step)-[:USES]->(r)" in captured["query"]


def test_generate_groovy_summary_writes_hash_keyed_cache(tmp_path):
    script = tmp_path / "example.groovy"
    script.write_text("message.setBody('done')", encoding="utf-8")

    class Response:
        text = ('{"purpose":"Sets the message body.","reads":[],"writes":["message body"],'
                '"side_effects":["none"],"complexity":"trivial","business_note":null}')

    class Client:
        class models:
            @staticmethod
            def generate_content(**_kwargs):
                return Response()

    cache_path = generate_groovy_summary(script, client=Client(), cache_dir=tmp_path / "cache")

    assert cache_path.is_file()
    assert cache_path.read_text(encoding="utf-8").find('"purpose": "Sets the message body."') != -1


def test_generate_all_groovy_summaries_deduplicates_using_resolver_hash(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "windows.groovy").write_bytes(b"message.setBody('done')\r\n")
    (source_root / "unix.groovy").write_bytes(b"message.setBody('done')\n")
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(groovy_summarizer, "_cache_dir", lambda: cache_dir)

    class Response:
        text = ('{"purpose":"Sets the message body.","reads":[],"writes":["message body"],'
                '"side_effects":["none"],"complexity":"trivial","business_note":null}')

    class Client:
        class models:
            @staticmethod
            def generate_content(**_kwargs):
                return Response()

    result = groovy_summarizer.generate_all_groovy_summaries(source_root, client=Client())

    assert result == {"scripts": 2, "generated": 1, "skipped": 1}
    assert len(list(cache_dir.glob("*.json"))) == 1
