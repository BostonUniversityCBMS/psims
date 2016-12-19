import warnings
from collections import Mapping, defaultdict
from functools import partial, update_wrapper

from .xml import (
    id_maker, CVParam, UserParam,
    _element)


class ChildTrackingMeta(type):
    def __new__(cls, name, parents, attrs):
        if not hasattr(cls, "_cache"):
            cls._cache = defaultdict(dict)
        new_type = type.__new__(cls, name, parents, attrs)
        ns = attrs.get("component_namespace", None)
        cls._cache[ns][name] = new_type
        return new_type

    @classmethod
    def resolve_component(self, namespace, name):
        try:
            return self._cache[namespace][name]
        except KeyError:
            return self._cache[None][name]


class SpecializedContextCache(dict):
    def __init__(self, type_name):
        self.type_name = type_name

    def __getitem__(self, key):
        try:
            item = dict.__getitem__(self, key)
            return item
        except KeyError:
            if key is None:
                return None
            warnings.warn("No reference was found for %r in %s" % (key, self.type_name), stacklevel=3)
            new_value = id_maker(self.type_name, key)
            self[key] = new_value
            return new_value

    def __repr__(self):
        return '%s\n%s' % (self.type_name, dict.__repr__(self))


class VocabularyResolver(object):
    def __init__(self, vocabularies=None):
        self.vocabularies = vocabularies

    def get_vocabulary(self, id):
        for vocab in self.vocabularies:
            if vocab.id == id:
                return vocab
        raise KeyError(id)

    def param(self, name, value=None, cv_ref=None, **kwargs):
        accession = kwargs.get("accession")
        if isinstance(name, CVParam):
            return name

        if isinstance(name, Mapping):
            mapping = name
            value = value or mapping.get('value')
            accession = accession or mapping.get("accession")
            cv_ref = cv_ref or mapping.get("cv_ref") or mapping.get("cvRef")
            name = mapping.get('name')

            kwargs.update({k: v for k, v in mapping.items() if k not in ("name", "value", "accession")})

        if cv_ref is None:
            for cv in self.vocabularies:
                try:
                    term = cv[name]
                    name = term["name"]
                    accession = term["id"]
                    cv_ref = cv.id
                except:
                    pass
        if cv_ref is None:
            return UserParam(name=name, value=value, **kwargs)
        else:
            kwargs.setdefault("ref", cv_ref)
            kwargs.setdefault("accession", accession)
            return CVParam(name=name, value=value, **kwargs)

    def term(self, name, include_source=False):
        for cv in self.vocabularies:
            try:
                term = cv[name]
                if include_source:
                    return term, cv
                else:
                    return term
            except:
                pass
        else:
            raise KeyError(name)


class DocumentContext(dict, VocabularyResolver):
    def __init__(self, vocabularies=None):
        dict.__init__(self)
        VocabularyResolver.__init__(self, vocabularies)

    def __missing__(self, key):
        self[key] = SpecializedContextCache(key)
        return self[key]


NullMap = DocumentContext()


class ReprBorrowingPartial(partial):
    """
    Create a partial instance that uses the wrapped callable's
    `__repr__` method instead of a generic partial
    """
    def __init__(self, func, *args, **kwargs):
        self._func = func
        super(ReprBorrowingPartial, self).__init__(func, *args, **kwargs)
        update_wrapper(self, func)

    def __repr__(self):
        return repr(self.func)

    def __getattr__(self, name):
        return getattr(self._func, name)


class ComponentDispatcherBase(object):
    """
    A container for a :class:`DocumentContext` which provides
    an automatically parameterized version of all :class:`ComponentBase`
    types which use this instance's context.

    Attributes
    ----------
    context : :class:`DocumentContext`
        The mapping responsible for managing the global
        state of all created components.
    """
    def __init__(self, context=None, vocabularies=None, component_namespace=None):
        if vocabularies is None:
            vocabularies = []
        if context is None:
            context = DocumentContext(vocabularies=vocabularies)
        else:
            if vocabularies is not None:
                context.vocabularies.extend(vocabularies)
        self.component_namespace = component_namespace
        self.context = context

    def __getattr__(self, name):
        """
        Provide access to an automatically parameterized
        version of all :class:`ComponentBase` types which
        use this instance's context.

        Parameters
        ----------
        name : str
            Component Name

        Returns
        -------
        ReprBorrowingPartial
            A partially parameterized instance constructor for
            the :class:`ComponentBase` type requested.
        """
        component = ChildTrackingMeta.resolve_component(self.component_namespace, name)
        return ReprBorrowingPartial(component, context=self.context)

    def register(self, entity_type, id):
        """
        Pre-declare an entity in the document context. Ensures that
        a reference look up will be satisfied.

        Parameters
        ----------
        entity_type : str
            An entity type, either a tag name or a component name
        id : int
            The unique id number for the thing registered

        Returns
        -------
        str
            The constructed reference id
        """
        value = id_maker(entity_type, id)
        self.context[entity_type][id] = value
        return value

    @property
    def vocabularies(self):
        return self.context.vocabularies

    def param(self, *args, **kwargs):
        return self.context.param(*args, **kwargs)

    def term(self, *args, **kwargs):
        return self.context.term(*args, **kwargs)

    def get_vocabulary(self, *args, **kwargs):
        return self.context.get_vocabulary(*args, **kwargs)

# ------------------------------------------
# Base Component Definitions


class ComponentBase(object):
    __metaclass__ = ChildTrackingMeta

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, key):
        try:
            return self.element.attrs[key]
        except KeyError:
            raise AttributeError(key)

    def write(self, xml_file):
        raise NotImplementedError()

    def __call__(self, xml_file):
        self.write(xml_file)

    def __repr__(self):
        return "%s\n%s" % (
            self.element, "\n".join([
                "  %s: %r" % (k, v) for k, v in self.__dict__.items()
                if k not in ("context", "element") and not k.startswith("_")])
        )


class ParameterContainer(ComponentBase):
    def __init__(self, tag_name, params=None, context=NullMap):
        if params is None:
            params = []
        self.element = _element(tag_name)
        self.context = context
        self.params = params

    def write(self, xml_file):
        with self.element(xml_file, with_id=False):
            for param in self.params:
                self.context.param(param)(xml_file)