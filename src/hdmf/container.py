import numpy as np
from abc import ABCMeta, abstractmethod
from uuid import uuid4
from collections import OrderedDict
from .utils import (docval, get_docval, call_docval_func, getargs, ExtenderMeta, get_data_shape, fmt_docval_args,
                    popargs, LabelledDict)
from .data_utils import DataIO, append_data, extend_data
from warnings import warn
import types


class AbstractContainer(metaclass=ExtenderMeta):

    # The name of the class attribute that subclasses use to autogenerate properties
    # This parameterization is supplied in case users would like to configure
    # the class attribute name to something domain-specific
    _fieldsname = '__fields__'

    _data_type_attr = 'data_type'

    # Subclasses use this class attribute to add properties to autogenerate
    # Autogenerated properties will store values in self.__field_values
    __fields__ = tuple()

    # This field is automatically set by __gather_fields before initialization.
    # It holds all the values in __fields__ for this class and its parent classes.
    __fieldsconf = tuple()

    _pconf_allowed_keys = {'name', 'doc', 'settable'}

    # Override the _setter factor function, so directives that apply to
    # Container do not get used on Data
    @classmethod
    def _setter(cls, field):
        """
        Make a setter function for creating a :py:func:`property`
        """
        name = field['name']

        if not field.get('settable', True):
            return None

        def setter(self, val):
            if val is None:
                return
            if name in self.fields:
                msg = "can't set attribute '%s' -- already set" % name
                raise AttributeError(msg)
            self.fields[name] = val

        return setter

    @classmethod
    def _getter(cls, field):
        """
        Make a getter function for creating a :py:func:`property`
        """
        doc = field.get('doc')
        name = field['name']

        def getter(self):
            return self.fields.get(name)

        setattr(getter, '__doc__', doc)
        return getter

    @staticmethod
    def _check_field_spec(field):
        """
        A helper function for __gather_fields to make sure we are always working
        with a dict specification and that the specification contains the correct keys
        """
        tmp = field
        if isinstance(tmp, dict):
            if 'name' not in tmp:
                raise ValueError("must specify 'name' if using dict in __fields__")
        else:
            tmp = {'name': tmp}
        return tmp

    @classmethod
    def _check_field_spec_keys(cls, field_conf):
        for k in field_conf:
            if k not in cls._pconf_allowed_keys:
                msg = ("Unrecognized key '%s' in %s config '%s' on %s"
                       % (k, cls._fieldsname, field_conf['name'], cls.__name__))
                raise ValueError(msg)

    @classmethod
    def _get_fields(cls):
        return getattr(cls, cls._fieldsname)

    @classmethod
    def _set_fields(cls, value):
        return setattr(cls, cls._fieldsname, value)

    @classmethod
    def get_fields_conf(cls):
        return cls.__fieldsconf

    @ExtenderMeta.pre_init
    def __gather_fields(cls, name, bases, classdict):
        '''
        This classmethod will be called during class declaration in the metaclass to automatically
        create setters and getters for fields that need to be exported
        '''
        fields = cls._get_fields()
        if not isinstance(fields, tuple):
            msg = "'%s' must be of type tuple" % cls._fieldsname
            raise TypeError(msg)

        # check field specs and create map from field name to field conf dictionary
        fields_dict = OrderedDict()
        for f in fields:
            pconf = cls._check_field_spec(f)
            cls._check_field_spec_keys(pconf)
            fields_dict[pconf['name']] = pconf
        all_fields_conf = list(fields_dict.values())

        # check whether this class overrides __fields__
        if len(bases):
            # find highest base class that is an AbstractContainer (parent is higher than children)
            base_cls = None
            for base_cls in reversed(bases):
                if issubclass(base_cls, AbstractContainer):
                    break
            base_fields = base_cls._get_fields()  # tuple of field names from base class
            if base_fields is not fields:
                # check whether new fields spec already exists in base class
                for field_name in fields_dict:
                    if field_name in base_fields:
                        warn("Field '%s' should not be defined in %s. It already exists on base class %s."
                             % (field_name, cls.__name__, base_cls.__name__))
                # prepend field specs from base class to fields list of this class
                all_fields_conf[0:0] = base_cls.get_fields_conf()

        # create getter and setter if attribute does not already exist
        # if 'doc' not specified in __fields__, use doc from docval of __init__
        docs = {dv['name']: dv['doc'] for dv in get_docval(cls.__init__)}
        for field_conf in all_fields_conf:
            pname = field_conf['name']
            field_conf.setdefault('doc', docs.get(pname))
            if not hasattr(cls, pname):
                setattr(cls, pname, property(cls._getter(field_conf), cls._setter(field_conf)))

        cls._set_fields(tuple(field_conf['name'] for field_conf in all_fields_conf))
        cls.__fieldsconf = tuple(all_fields_conf)

    def __new__(cls, *args, **kwargs):
        inst = super().__new__(cls)
        inst.__container_source = kwargs.pop('container_source', None)
        inst.__parent = None
        inst.__children = list()
        inst.__modified = True
        inst.__object_id = kwargs.pop('object_id', str(uuid4()))
        inst.parent = kwargs.pop('parent', None)
        return inst

    @docval({'name': 'name', 'type': str, 'doc': 'the name of this container'})
    def __init__(self, **kwargs):
        name = getargs('name', kwargs)
        if '/' in name:
            raise ValueError("name '" + name + "' cannot contain '/'")
        self.__name = name
        self.__field_values = dict()

    @property
    def name(self):
        '''
        The name of this Container
        '''
        return self.__name

    @docval({'name': 'data_type', 'type': str, 'doc': 'the data_type to search for', 'default': None})
    def get_ancestor(self, **kwargs):
        """
        Traverse parent hierarchy and return first instance of the specified data_type
        """
        data_type = getargs('data_type', kwargs)
        if data_type is None:
            return self.parent
        p = self.parent
        while p is not None:
            if getattr(p, p._data_type_attr) == data_type:
                return p
            p = p.parent
        return None

    @property
    def fields(self):
        return self.__field_values

    @property
    def object_id(self):
        if self.__object_id is None:
            self.__object_id = str(uuid4())
        return self.__object_id

    @docval({'name': 'recurse', 'type': bool,
             'doc': "whether or not to change the object ID of this container's children", 'default': True})
    def generate_new_id(self, **kwargs):
        """Changes the object ID of this Container and all of its children to a new UUID string."""
        recurse = getargs('recurse', kwargs)
        self.__object_id = str(uuid4())
        self.set_modified()
        if recurse:
            for c in self.children:
                c.generate_new_id(**kwargs)

    @property
    def modified(self):
        return self.__modified

    @docval({'name': 'modified', 'type': bool,
             'doc': 'whether or not this Container has been modified', 'default': True})
    def set_modified(self, **kwargs):
        modified = getargs('modified', kwargs)
        self.__modified = modified
        if modified and isinstance(self.parent, Container):
            self.parent.set_modified()

    @property
    def children(self):
        return tuple(self.__children)

    @docval({'name': 'child', 'type': 'Container',
             'doc': 'the child Container for this Container', 'default': None})
    def add_child(self, **kwargs):
        warn(DeprecationWarning('add_child is deprecated. Set the parent attribute instead.'))
        child = getargs('child', kwargs)
        if child is not None:
            # if child.parent is a Container, then the mismatch between child.parent and parent
            # is used to make a soft/external link from the parent to a child elsewhere
            # if child.parent is not a Container, it is either None or a Proxy and should be set to self
            if not isinstance(child.parent, AbstractContainer):
                # actually add the child to the parent in parent setter
                child.parent = self
        else:
            warn('Cannot add None as child to a container %s' % self.name)

    @classmethod
    def type_hierarchy(cls):
        return cls.__mro__

    @property
    def container_source(self):
        '''
        The source of this Container
        '''
        return self.__container_source

    @container_source.setter
    def container_source(self, source):
        if self.__container_source is not None:
            raise Exception('cannot reassign container_source')
        self.__container_source = source

    @property
    def parent(self):
        '''
        The parent Container of this Container
        '''
        # do it this way because __parent may not exist yet (not set in constructor)
        return getattr(self, '_AbstractContainer__parent', None)

    @parent.setter
    def parent(self, parent_container):
        if self.parent is parent_container:
            return

        if self.parent is not None:
            if isinstance(self.parent, AbstractContainer):
                raise ValueError(('Cannot reassign parent to Container: %s. '
                                  'Parent is already: %s.' % (repr(self), repr(self.parent))))
            else:
                if parent_container is None:
                    raise ValueError("Got None for parent of '%s' - cannot overwrite Proxy with NoneType" % repr(self))
                # NOTE this assumes isinstance(parent_container, Proxy) but we get a circular import
                # if we try to do that
                if self.parent.matches(parent_container):
                    self.__parent = parent_container
                    parent_container.__children.append(self)
                    parent_container.set_modified()
                else:
                    self.__parent.add_candidate(parent_container)
        else:
            self.__parent = parent_container
            if isinstance(parent_container, Container):
                parent_container.__children.append(self)
                parent_container.set_modified()

    def _remove_child(self, child):
        """Remove a child Container. Intended for use in subclasses that allow dynamic addition of child Containers."""
        if not isinstance(child, AbstractContainer):
            raise ValueError('Cannot remove non-AbstractContainer object from children.')
        if child not in self.children:
            raise ValueError("%s '%s' is not a child of %s '%s'." % (child.__class__.__name__, child.name,
                                                                     self.__class__.__name__, self.name))
        child.__parent = None
        self.__children.remove(child)
        child.set_modified()
        self.set_modified()


class Container(AbstractContainer):
    """A container that can contain other containers and has special functionality for printing."""

    _pconf_allowed_keys = {'name', 'child', 'required_name', 'doc', 'settable'}

    @classmethod
    def _setter(cls, field):
        """Returns a list of setter functions for the given field to be added to the class during class declaration."""
        super_setter = AbstractContainer._setter(field)
        ret = [super_setter]
        # create setter with check for required name
        if field.get('required_name', None) is not None:
            name = field['required_name']
            idx1 = len(ret) - 1

            def container_setter(self, val):
                if val is not None:
                    if not isinstance(val, AbstractContainer):
                        msg = ("Field '%s' on %s has a required name and must be a subclass of AbstractContainer."
                               % (field['name'], self.__class__.__name__))
                        raise ValueError(msg)
                    if val.name != name:
                        msg = ("Field '%s' on %s must be named '%s'."
                               % (field['name'], self.__class__.__name__, name))
                        raise ValueError(msg)
                ret[idx1](self, val)

            ret.append(container_setter)

        # create setter that accepts a value or tuple, list, or dict or values and sets the value's parent to self
        if field.get('child', False):
            idx2 = len(ret) - 1

            def container_setter(self, val):
                ret[idx2](self, val)
                if val is not None:
                    if isinstance(val, (tuple, list)):
                        pass
                    elif isinstance(val, dict):
                        val = val.values()
                    else:
                        val = [val]
                    for v in val:
                        if not isinstance(v.parent, Container):
                            v.parent = self
                        # else, the ObjectMapper will create a link from self (parent) to v (child with existing
                        # parent)

            ret.append(container_setter)
        return ret[-1]

    def __repr__(self):
        cls = self.__class__
        template = "%s %s.%s at 0x%d" % (self.name, cls.__module__, cls.__name__, id(self))
        if len(self.fields):
            template += "\nFields:\n"
        for k in sorted(self.fields):  # sorted to enable tests
            v = self.fields[k]
            # if isinstance(v, DataIO) or not hasattr(v, '__len__') or len(v) > 0:
            if hasattr(v, '__len__'):
                if isinstance(v, (np.ndarray, list, tuple)):
                    if len(v) > 0:
                        template += "  {}: {}\n".format(k, self.__smart_str(v, 1))
                elif v:
                    template += "  {}: {}\n".format(k, self.__smart_str(v, 1))
            else:
                template += "  {}: {}\n".format(k, v)
        return template

    @staticmethod
    def __smart_str(v, num_indent):
        """
        Print compact string representation of data.

        If v is a list, try to print it using numpy. This will condense the string
        representation of datasets with many elements. If that doesn't work, just print the list.

        If v is a dictionary, print the name and type of each element

        If v is a set, print it sorted

        If v is a neurodata_type, print the name of type

        Otherwise, use the built-in str()
        Parameters
        ----------
        v

        Returns
        -------
        str

        """

        if isinstance(v, list) or isinstance(v, tuple):
            if len(v) and isinstance(v[0], AbstractContainer):
                return Container.__smart_str_list(v, num_indent, '(')
            try:
                return str(np.asarray(v))
            except ValueError:
                return Container.__smart_str_list(v, num_indent, '(')
        elif isinstance(v, dict):
            return Container.__smart_str_dict(v, num_indent)
        elif isinstance(v, set):
            return Container.__smart_str_list(sorted(list(v)), num_indent, '{')
        elif isinstance(v, AbstractContainer):
            return "{} {}".format(getattr(v, 'name'), type(v))
        else:
            return str(v)

    @staticmethod
    def __smart_str_list(str_list, num_indent, left_br):
        if left_br == '(':
            right_br = ')'
        if left_br == '{':
            right_br = '}'
        if len(str_list) == 0:
            return left_br + ' ' + right_br
        indent = num_indent * 2 * ' '
        indent_in = (num_indent + 1) * 2 * ' '
        out = left_br
        for v in str_list[:-1]:
            out += '\n' + indent_in + Container.__smart_str(v, num_indent + 1) + ','
        if str_list:
            out += '\n' + indent_in + Container.__smart_str(str_list[-1], num_indent + 1)
        out += '\n' + indent + right_br
        return out

    @staticmethod
    def __smart_str_dict(d, num_indent):
        left_br = '{'
        right_br = '}'
        if len(d) == 0:
            return left_br + ' ' + right_br
        indent = num_indent * 2 * ' '
        indent_in = (num_indent + 1) * 2 * ' '
        out = left_br
        keys = sorted(list(d.keys()))
        for k in keys[:-1]:
            out += '\n' + indent_in + Container.__smart_str(k, num_indent + 1) + ' ' + str(type(d[k])) + ','
        if keys:
            out += '\n' + indent_in + Container.__smart_str(keys[-1], num_indent + 1) + ' ' + str(type(d[keys[-1]]))
        out += '\n' + indent + right_br
        return out


class Data(AbstractContainer):
    """
    A class for representing dataset containers
    """

    @docval({'name': 'name', 'type': str, 'doc': 'the name of this container'},
            {'name': 'data', 'type': ('scalar_data', 'array_data', 'data'), 'doc': 'the source of the data'})
    def __init__(self, **kwargs):
        call_docval_func(super().__init__, kwargs)
        self.__data = getargs('data', kwargs)

    @property
    def data(self):
        return self.__data

    @property
    def shape(self):
        """
        Get the shape of the data represented by this container
        :return: Shape tuple
        :rtype: tuple of ints
        """
        return get_data_shape(self.__data)

    @docval({'name': 'dataio', 'type': DataIO, 'doc': 'the DataIO to apply to the data held by this Data'})
    def set_dataio(self, **kwargs):
        """
        Apply DataIO object to the data held by this Data object
        """
        dataio = getargs('dataio', kwargs)
        dataio.data = self.__data
        self.__data = dataio

    @docval({'name': 'func', 'type': types.FunctionType, 'doc': 'a function to transform *data*'})
    def transform(self, **kwargs):
        """
        Transform data from the current underlying state.

        This function can be used to permanently load data from disk, or convert to a different
        representation, such as a torch.Tensor
        """
        func = getargs('func', kwargs)
        self.__data = func(self.__data)
        return self

    def __bool__(self):
        if self.data is not None:
            if isinstance(self.data, (np.ndarray, tuple, list)):
                return len(self.data) != 0
            if self.data:
                return True
        return False

    def __len__(self):
        return len(self.__data)

    def __getitem__(self, args):
        return self.get(args)

    def get(self, args):
        if isinstance(self.data, (tuple, list)) and isinstance(args, (tuple, list, np.ndarray)):
            return [self.data[i] for i in args]
        return self.data[args]

    def append(self, arg):
        self.__data = append_data(self.__data, arg)

    def extend(self, arg):
        self.__data = extend_data(self.__data, arg)


class DataRegion(Data):

    @property
    @abstractmethod
    def data(self):
        '''
        The target data that this region applies to
        '''
        pass

    @property
    @abstractmethod
    def region(self):
        '''
        The region that indexes into data e.g. slice or list of indices
        '''
        pass


def _not_parent(arg):
    return arg['name'] != 'parent'


class MultiContainerInterface(Container, metaclass=ABCMeta):
    """Class that dynamically defines methods to support a Container holding multiple Containers of the same type.

    To use, extend this class and create a dictionary as a class attribute with any of the following keys:
    * 'attr' to name the attribute that stores the Container instances
    * 'type' to provide the Container object type (type or list/tuple of types, type can be a docval macro)
    * 'add' to name the method for adding Container instances
    * 'get' to name the method for getting Container instances
    * 'create' to name the method for creating Container instances (only if a single type is specified)

    If the attribute does not exist in the class, it will be generated. If it does exist, it should behave like a dict.

    The keys 'attr', 'type', and 'add' are required.
    """

    @docval(*get_docval(Container.__init__))
    def __init__(self, **kwargs):
        call_docval_func(super().__init__, kwargs)

        if not hasattr(self.__class__, '__clsconf__'):
            # either the API was incorrectly defined or only a subclass with __clsconf__ can be initialized
            raise TypeError("Cannot initialize an instance of MultiContainerInterface subclass %s."
                            % self.__class__.__name__)

        # call this function whenever a container is removed from the dictionary
        def _remove_child(child):
            if child.parent is self:
                self._remove_child(child)

        if isinstance(self.__clsconf__, dict):
            attr_name = self.__clsconf__['attr']
            self.fields[attr_name] = LabelledDict(attr_name, remove_callable=_remove_child)
        else:
            for d in self.__clsconf__:
                attr_name = d['attr']
                self.fields[attr_name] = LabelledDict(attr_name, remove_callable=_remove_child)

    @staticmethod
    def __add_article(noun):
        if isinstance(noun, tuple):
            noun = noun[0]
        if isinstance(noun, type):
            noun = noun.__name__
        if noun[0] in ('aeiouAEIOU'):
            return 'an %s' % noun
        return 'a %s' % noun

    @staticmethod
    def __join(argtype):
        """Return a grammatical string representation of a list or tuple of classes or text.

        Examples:
        cls.__join(Container) returns "Container"
        cls.__join((Container, )) returns "Container"
        cls.__join((Container, Data)) returns "Container or Data"
        cls.__join((Container, Data, Subcontainer)) returns "Container, Data, or Subcontainer"
        """

        def tostr(x):
            return x.__name__ if isinstance(x, type) else x

        if isinstance(argtype, (list, tuple)):
            args_str = [tostr(x) for x in argtype]
            if len(args_str) == 1:
                return args_str[0]
            if len(args_str) == 2:
                return " or ".join(tostr(x) for x in args_str)
            else:
                return ", ".join(tostr(x) for x in args_str[:-1]) + ', or ' + args_str[-1]
        else:
            return tostr(argtype)

    @classmethod
    def __make_get(cls, func_name, attr_name, container_type):
        doc = "Get %s from this %s" % (cls.__add_article(container_type), cls.__name__)

        @docval({'name': 'name', 'type': str, 'doc': 'the name of the %s' % cls.__join(container_type),
                 'default': None},
                rtype=container_type, returns='the %s with the given name' % cls.__join(container_type),
                func_name=func_name, doc=doc)
        def _func(self, **kwargs):
            name = getargs('name', kwargs)
            d = getattr(self, attr_name)
            ret = None
            if name is None:
                if len(d) > 1:
                    msg = ("More than one element in %s of %s '%s' -- must specify a name."
                           % (attr_name, cls.__name__, self.name))
                    raise ValueError(msg)
                elif len(d) == 0:
                    msg = "%s of %s '%s' is empty." % (attr_name, cls.__name__, self.name)
                    raise ValueError(msg)
                else:  # only one item in dict
                    for v in d.values():
                        ret = v
            else:
                ret = d.get(name)
                if ret is None:
                    msg = "'%s' not found in %s of %s '%s'." % (name, attr_name, cls.__name__, self.name)
                    raise KeyError(msg)
            return ret

        return _func

    @classmethod
    def __make_getitem(cls, attr_name, container_type):
        doc = "Get %s from this %s" % (cls.__add_article(container_type), cls.__name__)

        @docval({'name': 'name', 'type': str, 'doc': 'the name of the %s' % cls.__join(container_type),
                 'default': None},
                rtype=container_type, returns='the %s with the given name' % cls.__join(container_type),
                func_name='__getitem__', doc=doc)
        def _func(self, **kwargs):
            # NOTE this is the same code as the getter but with different error messages
            name = getargs('name', kwargs)
            d = getattr(self, attr_name)
            ret = None
            if name is None:
                if len(d) > 1:
                    msg = ("More than one %s in %s '%s' -- must specify a name."
                           % (cls.__join(container_type), cls.__name__, self.name))
                    raise ValueError(msg)
                elif len(d) == 0:
                    msg = "%s '%s' is empty." % (cls.__name__, self.name)
                    raise ValueError(msg)
                else:  # only one item in dict
                    for v in d.values():
                        ret = v
            else:
                ret = d.get(name)
                if ret is None:
                    msg = "'%s' not found in %s '%s'." % (name, cls.__name__, self.name)
                    raise KeyError(msg)
            return ret

        return _func

    @classmethod
    def __make_add(cls, func_name, attr_name, container_type):
        doc = "Add %s to this %s" % (cls.__add_article(container_type), cls.__name__)

        @docval({'name': attr_name, 'type': (list, tuple, dict, container_type),
                 'doc': 'the %s to add' % cls.__join(container_type)},
                func_name=func_name, doc=doc)
        def _func(self, **kwargs):
            container = getargs(attr_name, kwargs)
            if isinstance(container, container_type):
                containers = [container]
            elif isinstance(container, dict):
                containers = container.values()
            else:
                containers = container
            d = getattr(self, attr_name)
            for tmp in containers:
                if not isinstance(tmp.parent, Container):
                    tmp.parent = self
                # else, the ObjectMapper will create a link from self (parent) to tmp (child with existing parent)
                if tmp.name in d:
                    msg = "'%s' already exists in %s '%s'" % (tmp.name, cls.__name__, self.name)
                    raise ValueError(msg)
                d[tmp.name] = tmp
            return container
        return _func

    @classmethod
    def __make_create(cls, func_name, add_name, container_type):
        doc = "Create %s and add it to this %s" % (cls.__add_article(container_type), cls.__name__)

        @docval(*filter(_not_parent, get_docval(container_type.__init__)), func_name=func_name, doc=doc,
                returns="the %s object that was created" % cls.__join(container_type), rtype=container_type)
        def _func(self, **kwargs):
            cargs, ckwargs = fmt_docval_args(container_type.__init__, kwargs)
            ret = container_type(*cargs, **ckwargs)
            getattr(self, add_name)(ret)
            return ret
        return _func

    @classmethod
    def __make_constructor(cls, clsconf):
        args = list()
        for conf in clsconf:
            attr_name = conf['attr']
            container_type = conf['type']
            args.append({'name': attr_name, 'type': (list, tuple, dict, container_type),
                         'doc': '%s to store in this interface' % cls.__join(container_type), 'default': dict()})

        args.append({'name': 'name', 'type': str, 'doc': 'the name of this container', 'default': cls.__name__})

        @docval(*args, func_name='__init__')
        def _func(self, **kwargs):
            call_docval_func(super(cls, self).__init__, kwargs)
            for conf in clsconf:
                attr_name = conf['attr']
                add_name = conf['add']
                container = popargs(attr_name, kwargs)
                add = getattr(self, add_name)
                add(container)
        return _func

    @classmethod
    def __make_setter(cls, nwbfield, add_name):

        @docval({'name': 'val', 'type': (list, tuple, dict), 'doc': 'the sub items to add', 'default': None})
        def _func(self, **kwargs):
            val = getargs('val', kwargs)
            if val is None:
                return
            getattr(self, add_name)(val)

        return _func

    @ExtenderMeta.pre_init
    def __build_class(cls, name, bases, classdict):
        """This will be called during class declaration in the metaclass to automatically create methods."""

        if not hasattr(cls, '__clsconf__'):
            return
        multi = False
        if isinstance(cls.__clsconf__, dict):
            clsconf = [cls.__clsconf__]
        elif isinstance(cls.__clsconf__, list):
            multi = True
            clsconf = cls.__clsconf__
        else:
            raise TypeError("'__clsconf__' for MultiContainerInterface subclass %s must be a dict or a list of "
                            "dicts." % cls.__name__)

        for conf_index, conf_dict in enumerate(clsconf):
            cls.__build_conf_methods(conf_dict, conf_index, multi)

        # make __getitem__ (square bracket access) only if one conf type is defined
        if len(clsconf) == 1:
            attr = clsconf[0].get('attr')
            container_type = clsconf[0].get('type')
            setattr(cls, '__getitem__', cls.__make_getitem(attr, container_type))

        # create the constructor, only if it has not been overridden
        # i.e. it is the same method as the parent class constructor
        if cls.__init__ == MultiContainerInterface.__init__:
            setattr(cls, '__init__', cls.__make_constructor(clsconf))

    @classmethod
    def __build_conf_methods(cls, conf_dict, conf_index, multi):
        # get add method name
        add = conf_dict.get('add')
        if add is None:
            msg = "MultiContainerInterface subclass %s is missing 'add' key in __clsconf__" % cls.__name__
            if multi:
                msg += " at index %d" % conf_index
            raise ValueError(msg)

        # get container attribute name
        attr = conf_dict.get('attr')
        if attr is None:
            msg = "MultiContainerInterface subclass %s is missing 'attr' key in __clsconf__" % cls.__name__
            if multi:
                msg += " at index %d" % conf_index
            raise ValueError(msg)

        # get container type
        container_type = conf_dict.get('type')
        if container_type is None:
            msg = "MultiContainerInterface subclass %s is missing 'type' key in __clsconf__" % cls.__name__
            if multi:
                msg += " at index %d" % conf_index
            raise ValueError(msg)

        # create property with the name given in 'attr' only if the attribute is not already defined
        if not hasattr(cls, attr):
            aconf = cls._check_field_spec(attr)
            getter = cls._getter(aconf)
            doc = "a dictionary containing the %s in this %s" % (cls.__join(container_type), cls.__name__)
            setattr(cls, attr, property(getter, cls.__make_setter(aconf, add), None, doc))

        # create the add method
        setattr(cls, add, cls.__make_add(add, attr, container_type))

        # create the create method, only if a single container type is specified
        create = conf_dict.get('create')
        if create is not None:
            if isinstance(container_type, type):
                setattr(cls, create, cls.__make_create(create, add, container_type))
            else:
                msg = ("Cannot specify 'create' key in __clsconf__ for MultiContainerInterface subclass %s "
                       "when 'type' key is not a single type") % cls.__name__
                if multi:
                    msg += " at index %d" % conf_index
                raise ValueError(msg)

        # create the get method
        get = conf_dict.get('get')
        if get is not None:
            setattr(cls, get, cls.__make_get(get, attr, container_type))
