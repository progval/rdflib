"""
This is a rdflib plugin for parsing Hextuple files, which are Newline-Delimited JSON
(ndjson) files, into Conjunctive. The store that backs the graph *must* be able to
handle contexts, i.e. multiple graphs.
"""

from __future__ import annotations

import json
import warnings
from io import TextIOWrapper
from typing import TYPE_CHECKING, Any, BinaryIO, List, Optional, TextIO, Union

from rdflib.graph import ConjunctiveGraph, Graph
from rdflib.parser import InputSource, Parser
from rdflib.term import BNode, Literal, URIRef

try:
    import orjson

    _HAS_ORJSON = True
except ImportError:
    orjson = None  # type: ignore[assignment, unused-ignore]
    _HAS_ORJSON = False

if TYPE_CHECKING:
    from io import BufferedReader

__all__ = ["HextuplesParser"]


class HextuplesParser(Parser):
    """
    An RDFLib parser for Hextuples

    """

    def __init__(self):
        self.skolemize = False

    def _parse_hextuple(
        self, cg: ConjunctiveGraph, tup: List[Union[str, None]]
    ) -> None:
        # all values check
        # subject, predicate, value, datatype cannot be None
        # language and graph may be None
        if tup[0] is None or tup[1] is None or tup[2] is None or tup[3] is None:
            raise ValueError(
                "subject, predicate, value, datatype cannot be None. Given: " f"{tup}"
            )

        # 1 - subject
        s: Union[URIRef, BNode]
        if tup[0].startswith("_"):
            s = BNode(value=tup[0].replace("_:", ""))
            if self.skolemize:
                s = s.skolemize()
        else:
            s = URIRef(tup[0])

        # 2 - predicate
        p = URIRef(tup[1])

        # 3 - value
        o: Union[URIRef, BNode, Literal]
        if tup[3] == "globalId":
            o = URIRef(tup[2])
        elif tup[3] == "localId":
            o = BNode(value=tup[2].replace("_:", ""))
            if self.skolemize:
                o = o.skolemize()
        else:  # literal
            if tup[4] is None:
                o = Literal(tup[2], datatype=URIRef(tup[3]))
            else:
                o = Literal(tup[2], lang=tup[4])

        # 6 - context
        if tup[5] is not None:
            c = (
                BNode(tup[5].replace("_:", ""))
                if tup[5].startswith("_:")
                else URIRef(tup[5])
            )
            if isinstance(c, BNode) and self.skolemize:
                c = c.skolemize()

            # type error: Argument 1 to "add" of "ConjunctiveGraph" has incompatible type "Tuple[Union[URIRef, BNode], URIRef, Union[URIRef, BNode, Literal], URIRef]"; expected "Union[Tuple[Node, Node, Node], Tuple[Node, Node, Node, Optional[Graph]]]"
            cg.add((s, p, o, c))  # type: ignore[arg-type]
        else:
            cg.add((s, p, o))

    # type error: Signature of "parse" incompatible with supertype "Parser"
    def parse(self, source: InputSource, graph: Graph, skolemize: bool = False, **kwargs: Any) -> None:  # type: ignore[override]
        if kwargs.get("encoding") not in [None, "utf-8"]:
            warnings.warn(
                f"Hextuples files are always utf-8 encoded, "
                f"I was passed: {kwargs.get('encoding')}, "
                "but I'm still going to use utf-8"
            )

        assert (
            graph.store.context_aware
        ), "Hextuples Parser needs a context-aware store!"

        self.skolemize = skolemize
        cg = ConjunctiveGraph(store=graph.store, identifier=graph.identifier)
        cg.default_context = graph

        try:
            text_stream: Optional[TextIO] = source.getCharacterStream()
        except (AttributeError, LookupError):
            text_stream = None
        try:
            binary_stream: Optional[BinaryIO] = source.getByteStream()
        except (AttributeError, LookupError):
            binary_stream = None

        if text_stream is None and binary_stream is None:
            raise ValueError(
                f"Source does not have a character stream or a byte stream and cannot be used {type(source)}"
            )
        if TYPE_CHECKING:
            assert text_stream is not None or binary_stream is not None
        use_stream: Union[TextIO, BinaryIO]
        if _HAS_ORJSON:
            if binary_stream is not None:
                use_stream = binary_stream
            else:
                if TYPE_CHECKING:
                    assert isinstance(text_stream, TextIOWrapper)
                use_stream = text_stream
            loads = orjson.loads
        else:
            if text_stream is not None:
                use_stream = text_stream
            else:
                if TYPE_CHECKING:
                    assert isinstance(binary_stream, BufferedReader)
                use_stream = TextIOWrapper(binary_stream, encoding="utf-8")
            loads = json.loads

        for line in use_stream:  # type: Union[str, bytes]
            if len(line) == 0 or line.isspace():
                # Skipping empty lines because this is what was being done before for the first and last lines, albeit in an rather indirect way.
                # The result is that we accept input that would otherwise be invalid.
                # Possibly we should just let this result in an error.
                continue
            # this complex handing is because the 'value' component is
            # allowed to be "" but not None
            # all other "" values are treated as None
            raw_line: List[str] = loads(line)
            hex_tuple_line = [x if x != "" else None for x in raw_line]
            if raw_line[2] == "":
                hex_tuple_line[2] = ""
            self._parse_hextuple(cg, hex_tuple_line)
