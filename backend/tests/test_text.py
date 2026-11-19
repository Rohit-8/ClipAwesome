from clipawesome import text as tx


def test_stem_groups_inflections():
    assert tx.stem("pricing") == tx.stem("price") == tx.stem("prices") == tx.stem("priced")
    assert tx.stem("running") == "run"
    assert tx.stem("business") == tx.stem("businesses")


def test_terms_drop_stopwords():
    assert tx.terms("So the PRICING of the product is what matters") == ["pric", "product", tx.stem("matter")]


def test_bm25_ranks_matching_doc_first():
    docs = [tx.terms(t) for t in ["we talk about cats", "pricing strategy for saas pricing", "random words here"]]
    scores = tx.BM25(docs).score(tx.query_weights("saas pricing"))
    assert scores.index(max(scores)) == 1
    assert scores[0] == 0 and scores[2] == 0


def test_query_weights_keywords_are_weaker():
    w = tx.query_weights("pricing", ["cost", "pricing"])
    assert w["pric"] == 1.0 and w["cost"] == 0.6


def test_find_timestamps():
    assert tx.find_timestamps("lol at 12:34 and 1:02:03, not 12:345 or 4:5") == [754, 3723]
    assert tx.find_timestamps("stream moment 123:45") == [123 * 60 + 45]
    assert tx.find_timestamps("0:59") == [59]


def test_fmt_and_shorten():
    assert tx.fmt_time(65) == "1:05"
    assert tx.fmt_time(3725) == "1:02:05"
    assert tx.shorten("one two three four", 10) == "one two…"


def test_matched_terms_and_keywords():
    found = tx.matched_terms("Pricing matters. Our prices changed.", tx.query_weights("price"))
    assert found == {"pricing": 1, "prices": 1}
    kws = tx.top_keywords("rocket rocket engine fuel", {"rocket": 1}, 10, 2)
    assert kws[0] == "rocket"
