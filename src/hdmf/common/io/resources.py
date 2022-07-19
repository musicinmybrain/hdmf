from .. import register_map
from ..resources import ExternalResources, KeyTable, ResourceTable, ObjectTable, ObjectKeyTable, EntityTable, ExternalResoucesFile
from ...build import ObjectMapper

# @register_map(ExternalResoucesFile)
# class ERFileMap(ObjectMapper):
#
#     def __init__(self, spec):
#         super().__init__(spec)
#
#         er_spec = spec.get_group('.external_resources')
#         self.map_spec('external_resources', er_spec)

@register_map(ExternalResources)
class ExternalResourcesMap(ObjectMapper):

    def construct_helper(self, name, parent_builder, table_cls, manager):
        """Create a new instance of table_cls with data from parent_builder[name].

           The DatasetBuilder for name is associated with data_type Data and container class Data,
           but users should use the more specific table_cls for these datasets.
        """
        parent = manager._get_proxy_builder(parent_builder)
        builder = parent_builder[name]
        src = builder.source
        oid = builder.attributes.get(self.spec.id_key())
        kwargs = dict(name=builder.name, data=builder.data)
        return self.__new_container__(table_cls, src, parent, oid, **kwargs)

    @ObjectMapper.constructor_arg('keys')
    def keys(self, builder, manager):
        return self.construct_helper('keys', builder, KeyTable, manager)

    @ObjectMapper.constructor_arg('resources')
    def resources(self, builder, manager):
        return self.construct_helper('resources', builder, ResourceTable, manager)

    @ObjectMapper.constructor_arg('entities')
    def entities(self, builder, manager):
        return self.construct_helper('entities', builder, EntityTable, manager)

    @ObjectMapper.constructor_arg('objects')
    def objects(self, builder, manager):
        return self.construct_helper('objects', builder, ObjectTable, manager)

    @ObjectMapper.constructor_arg('object_keys')
    def object_keys(self, builder, manager):
        return self.construct_helper('object_keys', builder, ObjectKeyTable, manager)
