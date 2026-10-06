from api.streaming import AnswerSplitter, SENTINEL


def feed_all(tokens):
    sp = AnswerSplitter()
    emitted = ""
    for t in tokens:
        emitted += sp.feed(t)
    emitted += sp.finish()
    return sp, emitted


def test_no_sentinel_all_answer():
    sp, emitted = feed_all(["Hola", " mundo", "."])
    assert emitted == "Hola mundo."
    assert sp.answer_text() == "Hola mundo."
    assert sp.suggestions() == []


def test_sentinel_splits_answer_and_suggestions():
    tokens = [
        "DAM tiene módulos.",
        "\n[[SEGUIMIENTO]]\n",
        "- ¿Plazo de matrícula?\n",
        "- ¿Salidas?\n",
    ]
    sp, emitted = feed_all(tokens)
    assert emitted.strip() == "DAM tiene módulos."
    assert sp.answer_text().strip() == "DAM tiene módulos."
    assert sp.suggestions() == ["¿Plazo de matrícula?", "¿Salidas?"]


def test_sentinel_split_across_tokens():
    # El centinela llega partido en dos tokens: no debe filtrarse al texto.
    tokens = ["Respuesta.", "\n[[SEGUI", "MIENTO]]\n", "- Uno\n"]
    sp, emitted = feed_all(tokens)
    assert emitted.strip() == "Respuesta."
    assert "SEGUI" not in emitted
    assert sp.suggestions() == ["Uno"]


def test_suggestions_cleaned_and_capped_at_three():
    tail = "[[SEGUIMIENTO]]\n- A\n\n- B\nC\n- D\n"
    sp, _ = feed_all(["Texto. ", tail])
    # vacías descartadas, guion opcional, recortado a 3
    assert sp.suggestions() == ["A", "B", "C"]


def test_sentinel_is_double_bracket_constant():
    assert SENTINEL == "[[SEGUIMIENTO]]"
