from abc import ABCMeta, abstractmethod

from ..build import BuildManager, GroupBuilder
from ..utils import docval, getargs, popargs
from ..container import Container


class HDMFIO(metaclass=ABCMeta):
    @docval({'name': 'manager', 'type': BuildManager,
             'doc': 'the BuildManager to use for I/O', 'default': None},
            {"name": "source", "type": str,
             "doc": "the source of container being built i.e. file path", 'default': None})
    def __init__(self, **kwargs):
        self.__manager = getargs('manager', kwargs)
        self.__built = dict()
        self.__source = getargs('source', kwargs)
        self.open()

    @property
    def manager(self):
        '''The BuildManager this HDMFIO is using'''
        return self.__manager

    @property
    def source(self):
        '''The source of the container being read/written i.e. file path'''
        return self.__source

    @docval(returns='the Container object that was read in', rtype=Container)
    def read(self, **kwargs):
        f_builder = self.read_builder()
        if all(len(v) == 0 for v in f_builder.values()):
            # TODO also check that the keys are appropriate. print a better error message
            raise UnsupportedOperation('Cannot build data. There are no values.')
        container = self.__manager.construct(f_builder)
        return container

    @docval({'name': 'container', 'type': Container, 'doc': 'the Container object to write'},
            {'name': 'exhaust_dci', 'type': bool,
             'doc': 'exhaust DataChunkIterators one at a time. If False, exhaust them concurrently', 'default': True})
    def write(self, **kwargs):
        container = popargs('container', kwargs)
        f_builder = self.__manager.build(container, source=self.__source)
        self.write_builder(f_builder, **kwargs)

    @docval({'name': 'src_io', 'type': 'HDMFIO', 'doc': 'the HDMFIO object for reading the data to export'},
            {'name': 'container', 'type': Container,
             'doc': ('the Container object to export. If None, then the entire contents of the HDMFIO object will be '
                     'exported'),
             'default': None},
            {'name': 'read_args', 'type': dict, 'doc': 'dict of arguments to use when calling read_io.read_builder',
             'default': dict()},
            {'name': 'write_args', 'type': dict, 'doc': 'dict of arguments to use when calling write_io.write_builder',
             'default': dict()})
    def export(self, **kwargs):
        """Export from one backend to another.

        If container is provided, then the build manager of src_io is used to build the container, and the resulting
        builder will be exported to the new backend. So if container is provided, src_io must have a non-None manager
        property. If container is None, then the contents of src_io will be read and exported to the new backend.

        Arguments can be passed in for the read_builder and write_builder methods. By default, all external links
        will be resolved (i.e., the exported file will have no external links).

        Some arguments in `write_args` may not be supported during export.

        Example usage:

            old_io = HDF5IO('old.nwb', 'r')
            with HDF5IO('new_copy.nwb', 'w') as new_io:
                new_io.export(old_io)
        """
        src_io, container, read_args, write_args = getargs('src_io', 'container', 'read_args', 'write_args', kwargs)
        if container is not None:
            if src_io.manager is None:
                raise ValueError('When a container is provided, src_io must have a non-None manager (BuildManager) '
                                 'property.')
            bldr = src_io.manager.build(container)
        else:
            bldr = src_io.read_builder(**read_args)
        self.write_builder(builder=bldr, **write_args)

    @abstractmethod
    @docval(returns='a GroupBuilder representing the read data', rtype='GroupBuilder')
    def read_builder(self):
        ''' Read data and return the GroupBuilder representing it '''
        pass

    @abstractmethod
    @docval({'name': 'builder', 'type': GroupBuilder, 'doc': 'the GroupBuilder object representing the Container'},
            {'name': 'exhaust_dci', 'type': bool,
             'doc': 'exhaust DataChunkIterators one at a time. If False, exhaust them concurrently', 'default': True})
    def write_builder(self, **kwargs):
        ''' Write a GroupBuilder representing an Container object '''
        pass

    @abstractmethod
    def open(self):
        ''' Open this HDMFIO object for writing of the builder '''
        pass

    @abstractmethod
    def close(self):
        ''' Close this HDMFIO object to further reading/writing'''
        pass

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()


class UnsupportedOperation(ValueError):
    pass
