import importlib
import os
import json
import uuid

from paste.reloader import watch_file
from paste.deploy.converters import asbool
from pylons.i18n import _
import ckan.plugins as p
from ckan.lib.plugins import DefaultDatasetForm

from ckanext.recombinant import logic, tables

try:
    import yaml
except ImportError:
    yaml = None

class RecombinantException(Exception):
    pass


class RecombinantPlugin(p.SingletonPlugin, DefaultDatasetForm):
    p.implements(tables.IRecombinant)
    p.implements(p.IConfigurer)
    p.implements(p.IDatasetForm, inherit=True)
    p.implements(p.IRoutes, inherit=True)
    p.implements(p.ITemplateHelpers, inherit=True)
    p.implements(p.IActions)

    def update_config(self, config):
        # add our templates
        p.toolkit.add_template_directory(config, 'templates')

        # read our configuration early
        self._tables_urls = config.get('recombinant.tables', ""
            ).split()
        if not self._tables_urls:
            raise RecombinantException("Missing configuration option "
                "recombinant.tables")
        self._tables = _load_tables(self._tables_urls)

    def package_types(self):
        return list(set(t['dataset_type'] for t in self._tables))

    def read_template(self):
        return 'recombinant/edit.html'

    def edit_template(self):
        return 'recombinant/edit.html'

    def create_package_schema(self):
        schema = super(RecombinantPlugin, self).create_package_schema()
        schema['id'] = [generate_uuid]
        schema['name'] = [value_from_id]
        schema['resources']['url'] = [p.toolkit.get_validator('ignore_missing')]

        return schema

    def before_map(self, map):
        map.connect('/recombinant/upload/{id}', action='upload',
            conditions=dict(method=['POST']),
            controller='ckanext.recombinant.controller:UploadController')
        map.connect('/recombinant/delete/{id}', action='delete_record',
            conditions=dict(method=['POST']),
            controller='ckanext.recombinant.controller:UploadController')
        map.connect('/recombinant/template/{id}', action='template',
            controller='ckanext.recombinant.controller:UploadController')
        return map

    def get_helpers(self):
        return {
            'recombinant_primary_key_fields': primary_key_fields,
            'recombinant_get_table': recombinant_get_table,
            'recombinant_example': recombinant_example,
            }

    def get_actions(self):
        return {
            'recombinant_create': logic.recombinant_create,
            'recombinant_update': logic.recombinant_update,
            }


def generate_uuid(value):
    """
    Create an id for this dataset earlier than normal.
    """
    return str(uuid.uuid4())


def value_from_id(key, converted_data, errors, context):
    """
    Copy the 'id' value from converted_data
    """
    converted_data[key] = converted_data[('id',)]


def _load_tables(urls):
    tables = []
    for url in urls:
        t = _load_tables_module_path(url)
        if not t:
            t = _load_tables_url(url)

        for r in t['resources']:
            r['dataset_type'] = t['dataset_type']
            r['target_dataset'] = t['target_dataset']
            tables.append(r)

    return tables


def _load_tables_module_path(url):
    """
    Given a path like "ckanext.spatialx:recombinant_tables.json"
    find the second part relative to the import path of the first

    returns None if not found
    """
    module, file_name = url.split(':', 1)
    try:
        m = importlib.import_module(module)
    except ImportError:
        return
    p = m.__path__[0]
    p = os.path.join(p, file_name)
    if os.path.exists(p):
        watch_file(p)
        return load(open(p))


def _load_tables_url(url):
    import urllib2
    try:
        res = urllib2.urlopen(url)
        tables = res.read()
    except urllib2.URLError:
        raise RecombinantException("Could not find recombinant.tables json config file: %s" % url )

    return loads(tables, url)


def load(f):
    if is_yaml(f.name):
        return yaml.load(f)
    return json.load(f)


def loads(s, url):
    if is_yaml(url):
        return yaml.load(s)
    return json.loads(s)


def is_yaml(n):
    # import pyyaml only if necessary
    return n.endswith(('.yaml', '.yml'))


def primary_key_fields(dataset_type):
    t = get_table(dataset_type)
    return [
        f for f in t['fields']
        if f['datastore_id'] in t['datastore_primary_key']
        ]

def recombinant_get_table(sheet_name):
    try:
        return get_table(sheet_name)
    except RecombinantException:
        return

def recombinant_example(sheet_name, doc_type, indent=2, lang='json'):
    """
    Return example data formatted for use in API documentation
    """
    t = recombinant_get_table(sheet_name)
    if t and doc_type in t.get('examples', {}):
        data = t['examples'][doc_type]
    elif doc_type == 'sort':
        data = "request_date desc, file_number asc"
    elif doc_type == 'filters':
        data = {"resource": "doc", "priority": "high"}
    elif doc_type == 'filter_one':
        data = {"file_number": "86086"}
    else:
        data = {
            "request_date": "2016-01-01",
            "file_number": "42042",
            "resource": "doc",
            "prioroty": "low",
        }

    if not isinstance(data, (list, dict)):
        return json.dumps(data)

    left = ' ' * indent

    if lang == 'pythonargs':
        return ',\n'.join(
            "%s%s=%s" % (left, k, json.dumps(data[k]))
            for k in sorted(data))

    out = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    return left[2:] + ('\n' + left[2:]).join(out.split('\n')[1:-1])
