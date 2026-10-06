SENTINEL = "[[SEGUIMIENTO]]"
_HOLD = len(SENTINEL) - 1  # chars retenidos por si el centinela cruza tokens


class AnswerSplitter:
    """Trocea el stream del LLM: prosa de respuesta vs cola de seguimientos.

    Uso: feed(token) por cada token (devuelve texto de respuesta seguro para
    emitir ya, puede ser ''); finish() al acabar (vacía el buffer retenido).
    answer_text() = prosa completa para persistir; suggestions() = lista limpia.
    """

    def __init__(self) -> None:
        self._buf = ""        # buffer del lado respuesta (con holdback)
        self._tail = ""       # todo lo posterior al centinela
        self._answer = ""     # prosa de respuesta acumulada
        self._in_tail = False

    def feed(self, token: str) -> str:
        if self._in_tail:
            self._tail += token
            return ""
        self._buf += token
        idx = self._buf.find(SENTINEL)
        if idx != -1:
            emit = self._buf[:idx]
            self._tail = self._buf[idx + len(SENTINEL):]
            self._in_tail = True
            self._buf = ""
            self._answer += emit
            return emit
        # Retener los últimos _HOLD chars: podrían ser el inicio del centinela.
        if len(self._buf) > _HOLD:
            emit = self._buf[:-_HOLD]
            self._buf = self._buf[-_HOLD:]
            self._answer += emit
            return emit
        return ""

    def finish(self) -> str:
        if self._in_tail:
            return ""
        emit = self._buf
        self._buf = ""
        self._answer += emit
        return emit

    def answer_text(self) -> str:
        return self._answer

    def suggestions(self) -> list[str]:
        out = []
        for line in self._tail.splitlines():
            s = line.strip()
            if s.startswith("-"):
                s = s[1:].strip()
            if s:
                out.append(s)
        return out[:3]
