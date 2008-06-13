from landscape.tests.helpers import LandscapeTest

from landscape.schema import (
    InvalidError, Constant, Bool, Int, Float, String, Unicode, UnicodeOrString,
    List, KeyDict, Dict, Tuple,
    Any, Message)



class DummySchema(object):
    def coerce(self, value):
        return "hello!"


class BasicTypesTest(LandscapeTest):

    def test_any(self):
        schema = Any(Constant(None), Unicode())
        self.assertEquals(schema.coerce(None), None)
        self.assertEquals(schema.coerce(u"foo"), u"foo")

    def test_any_bad(self):
        schema = Any(Constant(None), Unicode())
        self.assertRaises(InvalidError, schema.coerce, object())

    def test_constant(self):
        self.assertEquals(Constant("hello").coerce("hello"), "hello")

    def test_constant_arbitrary(self):
        obj = object()
        self.assertEquals(Constant(obj).coerce(obj), obj)

    def test_constant_bad(self):
        self.assertRaises(InvalidError, Constant("foo").coerce, object())

    def test_bool(self):
        self.assertEquals(Bool().coerce(True), True)
        self.assertEquals(Bool().coerce(False), False)

    def test_bool_bad(self):
        self.assertRaises(InvalidError, Bool().coerce, 1)


    def test_int(self):
        self.assertEquals(Int().coerce(3), 3)

    def test_int_accepts_long(self):
        self.assertEquals(Int().coerce(3L), 3)

    def test_int_bad_str(self):
        self.assertRaises(InvalidError, Int().coerce, "3")

    def test_int_bad_float(self):
        self.assertRaises(InvalidError, Int().coerce, 3.0)


    def test_float(self):
        self.assertEquals(Float().coerce(3.3), 3.3)

    def test_float_accepts_int(self):
        self.assertEquals(Float().coerce(3), 3.0)

    def test_float_accepts_long(self):
        self.assertEquals(Float().coerce(3L), 3.0)

    def test_float_bad_str(self):
        self.assertRaises(InvalidError, Float().coerce, "3.0")


    def test_string(self):
        self.assertEquals(String().coerce("foo"), "foo")

    def test_string_bad_unicode(self):
        self.assertRaises(InvalidError, String().coerce, u"foo")

    def test_string_bad_anything(self):
        self.assertRaises(InvalidError, String().coerce, object())


    def test_unicode(self):
        self.assertEquals(Unicode().coerce(u"foo"), u"foo")

    def test_unicode_bad_str(self):
        self.assertRaises(InvalidError, Unicode().coerce, "foo")


    def test_unicode_or_str(self):
        self.assertEquals(UnicodeOrString("utf-8").coerce(u"foo"), u"foo")

    def test_unicode_or_str_bad(self):
        self.assertRaises(InvalidError, Unicode().coerce, 32)

    def test_unicode_or_str_accepts_str(self):
        self.assertEquals(UnicodeOrString("utf-8").coerce("foo"), u"foo")

    def test_unicode_or_str_decodes(self):
        """UnicodeOrString should decode plain strings."""
        a = u"\N{HIRAGANA LETTER A}"
        self.assertEquals(
            UnicodeOrString("utf-8").coerce(a.encode("utf-8")),
            a)
        letter = u"\N{LATIN SMALL LETTER A WITH GRAVE}"
        self.assertEquals(
            UnicodeOrString("latin-1").coerce(letter.encode("latin-1")),
            letter)

    def test_unicode_or_str_bad_encoding(self):
        """Decoding errors should be converted to InvalidErrors."""
        schema = UnicodeOrString("utf-8")
        self.assertRaises(InvalidError, schema.coerce, "\xff")


    def test_list(self):
        self.assertEquals(List(Int()).coerce([1]), [1])

    def test_list_bad(self):
        self.assertRaises(InvalidError, List(Int()).coerce, 32)

    def test_list_inner_schema_coerces(self):
        self.assertEquals(List(DummySchema()).coerce([3]), ["hello!"])

    def test_list_bad_inner_schema(self):
        self.assertRaises(InvalidError, List(Int()).coerce, ["hello"])

    def test_list_multiple_items(self):
        a = u"\N{HIRAGANA LETTER A}"
        schema = List(UnicodeOrString("utf-8"))
        self.assertEquals(schema.coerce([a, a.encode("utf-8")]), [a, a])


    def test_tuple(self):
        self.assertEquals(Tuple(Int()).coerce((1,)), (1,))

    def test_tuple_coerces(self):
        self.assertEquals(Tuple(Int(), DummySchema()).coerce((23, object())),
                          (23, "hello!"))

    def test_tuple_bad(self):
        self.assertRaises(InvalidError, Tuple().coerce, object())

    def test_tuple_inner_schema_bad(self):
        self.assertRaises(InvalidError, Tuple(Int()).coerce, (object(),))

    def test_tuple_must_have_all_items(self):
        self.assertRaises(InvalidError, Tuple(Int(), Int()).coerce, (1,))

    def test_tuple_must_have_no_more_items(self):
        self.assertRaises(InvalidError, Tuple(Int()).coerce, (1, 2))


    def test_key_dict(self):
        self.assertEquals(KeyDict({"foo": Int()}).coerce({"foo": 1}),
                          {"foo": 1})

    def test_key_dict_coerces(self):
        self.assertEquals(KeyDict({"foo": DummySchema()}).coerce({"foo": 3}),
                          {"foo": "hello!"})

    def test_key_dict_bad_inner_schema(self):
        self.assertRaises(InvalidError, KeyDict({"foo": Int()}).coerce,
                          {"foo": "hello"})

    def test_key_dict_unknown_key(self):
        self.assertRaises(InvalidError, KeyDict({}).coerce, {"foo": 1})

    def test_key_dict_bad(self):
        self.assertRaises(InvalidError, KeyDict({}).coerce, object())

    def test_key_dict_multiple_items(self):
        schema = KeyDict({"one": Int(), "two": List(Float())})
        input = {"one": 32, "two": [1.5, 2.3]}
        self.assertEquals(schema.coerce(input),
                          {"one": 32, "two": [1.5, 2.3]})

    def test_key_dict_arbitrary_keys(self):
        """
        KeyDict doesn't actually need to have strings as keys, just any
        object which hashes the same.
        """
        key = object()
        self.assertEquals(KeyDict({key: Int()}).coerce({key: 32}), {key: 32})

    def test_key_dict_must_have_all_keys(self):
        """
        dicts which are applied to a KeyDict must have all the keys
        specified in the KeyDict.
        """
        schema = KeyDict({"foo": Int()})
        self.assertRaises(InvalidError, schema.coerce, {})

    def test_key_dict_optional_keys(self):
        """KeyDict allows certain keys to be optional.
        """
        schema = KeyDict({"foo": Int(), "bar": Int()}, optional=["bar"])
        self.assertEquals(schema.coerce({"foo": 32}), {"foo": 32})

    def test_pass_optional_key(self):
        """Regression test. It should be possible to pass an optional key.
        """
        schema = KeyDict({"foo": Int()}, optional=["foo"])
        self.assertEquals(schema.coerce({"foo": 32}), {"foo": 32})

    def test_dict(self):
        self.assertEquals(Dict(Int(), String()).coerce({32: "hello."}),
                          {32: "hello."})

    def test_dict_coerces(self):
        self.assertEquals(
            Dict(DummySchema(), DummySchema()).coerce({32: object()}),
            {"hello!": "hello!"})

    def test_dict_inner_bad(self):
        self.assertRaises(InvalidError, Dict(Int(), Int()).coerce, {"32": 32})

    def test_dict_wrong_type(self):
        self.assertRaises(InvalidError, Dict(Int(), Int()).coerce, 32)


    def test_message(self):
        """The L{Message} schema should be very similar to KeyDict."""
        schema = Message("foo", {"data": Int()})
        self.assertEquals(
            schema.coerce({"type": "foo", "data": 3}),
            {"type": "foo", "data": 3})

    def test_message_timestamp(self):
        """L{Message} schemas should accept C{timestamp} keys."""
        schema = Message("bar", {})
        self.assertEquals(
            schema.coerce({"type": "bar", "timestamp": 0.33}),
            {"type": "bar", "timestamp": 0.33})

    def test_message_api(self):
        """L{Message} schemas should accept C{api} keys."""
        schema = Message("baz", {})
        self.assertEquals(
            schema.coerce({"type": "baz", "api": "whatever"}),
            {"type": "baz", "api": "whatever"})

    def test_message_api_None(self):
        """L{Message} schemas should accept None for C{api}."""
        schema = Message("baz", {})
        self.assertEquals(
            schema.coerce({"type": "baz", "api": None}),
            {"type": "baz", "api": None})

    def test_message_optional(self):
        """The L{Message} schema should allow additional optional keys."""
        schema = Message("foo", {"data": Int()}, optional=["data"])
        self.assertEquals(schema.coerce({"type": "foo"}), {"type": "foo"})

    def test_message_type(self):
        """The C{type} should be introspectable on L{Message} objects."""
        schema = Message("foo", {})
        self.assertEquals(schema.type, "foo")