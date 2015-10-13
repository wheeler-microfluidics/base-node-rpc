from datetime import datetime
import warnings

from paver.easy import task, needs, path, sh, cmdopts, options
import base_node_rpc
try:
    from arduino_rpc.pavement_base import *
except ImportError:
    # Ignore import error to allow import during installation of
    # `base-node-rpc` (i.e., prior to the installation of `arduino-rpc` through
    # install dependencies).
    LIB_CMDOPTS = None
    LIB_GENERATE_TASKS = None


DEFAULT_BASE_CLASSES = ['BaseNodeSerialHandler', 'BaseNodeEeprom',
                        'BaseNodeI2c', 'BaseNodeI2cHandler<Handler>']
DEFAULT_METHODS_FILTER = lambda df: df[~(df.method_name
                                         .isin(['get_config_fields',
                                                'get_state_fields']))].copy()
prefix = 'base_node_rpc.pavement_base.'


def get_base_classes_and_headers(options, lib_dir, sketch_dir):
    '''
    Return ordered list of classes to scan for method discovery, along with a
    corresponding list of the header file where each class may be found.

     - Base classes refer to classes that are to be found in the
       `base-node-rpc` library directory.
     - rpc classes refer to classes found in the sketch directory.
    '''

    package_name = options.PROPERTIES['package_name']
    module_name = package_name.replace('-', '_')
    base_classes = getattr(options, 'base_classes', DEFAULT_BASE_CLASSES)
    rpc_classes = getattr(options, 'rpc_classes', [module_name + '::Node'])

    input_classes = ['BaseNode'] + base_classes + rpc_classes
    base_node_lib_dir = lib_dir.joinpath('BaseNodeRpc', 'src', 'BaseNodeRpc')
    input_headers = ([base_node_lib_dir.joinpath('BaseNode.h')] +
                     [base_node_lib_dir.joinpath('%s.h' % c.split('<')[0])
                      for c in base_classes] +
                     len(rpc_classes) * [sketch_dir.joinpath('Node.h')])
    return input_classes, input_headers


def generate_validate_header(message_name, sketch_dir):
    '''
    If package has generated Python `config` module and a Protocol Buffer
    message class type with the specified message name is defined, scan node
    base classes for callback methods related to the message type.

    For example, if the message name is `Config`, callbacks of the form
    `on_config_<field name>_changed` will be matched.
    '''
    from importlib import import_module

    from path_helpers import path
    import c_array_defs
    from .protobuf import (get_handler_validator_class_code,
                           write_handler_validator_header)
    from . import get_lib_directory

    try:
        config = import_module('.config', package=options.rpc_module.__name__)
    except ImportError:
        warnings.warn('ImportError: could not import %s.config' %
                      options.rpc_module.__name__)
        return

    lib_dir = get_lib_directory()
    if hasattr(config, message_name):
        package_name = sketch_dir.name
        input_classes, input_headers = get_base_classes_and_headers(options,
                                                                    lib_dir,
                                                                    sketch_dir)
        message_type = getattr(config, message_name)
        args = ['-I%s' % p for p in [lib_dir.abspath()] +
                c_array_defs.get_includes()]
        validator_code = get_handler_validator_class_code(input_headers,
                                                          input_classes,
                                                          message_type, *args)

        output_path = path(sketch_dir).joinpath('%s_%s_validate.h' %
                                                (package_name,
                                                 message_name.lower()))
        write_handler_validator_header(output_path, package_name,
                                       message_name.lower(), validator_code)


@task
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_rpc_buffer_header(options):
    import arduino_rpc.rpc_data_frame as rpc_df
    sketch_dir = options.rpc_module.get_sketch_directory()
    rpc_df.generate_rpc_buffer_header(sketch_dir, source_dir=sketch_dir)


@task
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_command_processor_header(options):
    '''
    Generate the following headers in a project directory under
    `Arduino/library`:

     - `Commands.h`
     - `Properties.h`
     - `CommandProcessor.h`

    ## `Commands.h` ##

    This header defines the 8-bit code and request/response C structures
    associated with each command type.  This header can, for example, be
    included by other projects to make requests through i2c.

    ## `Properties.h` ##

    Contains property string define statements (e.g. `BASE_NODE__NAME`).

    ## `CommandProcessor.h` ##

    Contains the `CommandProcessor` C++ class for the project.

    ## `NodeCommandProcessor.h` ##

    This header is written to the sketch directory and simply includes the
    three library headers above.
    '''
    from arduino_rpc.code_gen import write_code, C_GENERATED_WARNING_MESSAGE
    from arduino_rpc.rpc_data_frame import (get_c_commands_header_code,
                                            get_c_command_processor_header_code)
    from clang_helpers.data_frame import underscore_to_camelcase
    import c_array_defs
    import jinja2

    package_name = options.PROPERTIES['package_name']
    module_name = package_name.replace('-', '_')
    sketch_dir = path(module_name).joinpath('Arduino', module_name)
    lib_dir = base_node_rpc.get_lib_directory()

    input_classes, input_headers = get_base_classes_and_headers(options,
                                                                lib_dir,
                                                                sketch_dir)
    camel_name = underscore_to_camelcase(module_name)

    sketch_dir = path(module_name).joinpath('Arduino', module_name)
    project_lib_dir = verify_library_directory(options)
    arduino_src_dir = project_lib_dir.joinpath('src', project_lib_dir.name)
    if not arduino_src_dir.isdir():
        arduino_src_dir.makedirs_p()

    with arduino_src_dir.joinpath('Properties.h').open('wb') as output:
        print >> output, C_GENERATED_WARNING_MESSAGE % datetime.now()
        print >> output, '#ifndef ___%s__PROPERTIES___' % module_name.upper()
        print >> output, '#define ___%s__PROPERTIES___' % module_name.upper()
        print >> output, ''
        for k, v in options.PROPERTIES.iteritems():
            print >> output, '#ifndef BASE_NODE__%s' % k.upper()
            print >> output, '#define BASE_NODE__%s  ("%s")' % (k.upper(), v)
            print >> output, '#endif'
        print >> output, ''
        print >> output, '#endif'

    with sketch_dir.joinpath('NodeCommandProcessor.h').open('wb') as output:
        template = jinja2.Template('''\
#ifndef ___{{ name.upper()  }}___
#define ___{{ name.upper()  }}___

#include "{{ camel_name }}/Properties.h"
#include "{{ camel_name }}/CommandProcessor.h"

#endif  // #ifndef ___{{ name.upper()  }}___''')
        print >> output, C_GENERATED_WARNING_MESSAGE % datetime.now()
        print >> output, template.render(name=module_name,
                                         camel_name=camel_name)
        print >> output, ''

    headers = {'Commands': get_c_commands_header_code,
               'CommandProcessor': get_c_command_processor_header_code}

    methods_filter = getattr(options, 'methods_filter', DEFAULT_METHODS_FILTER)

    for k, f in headers.iteritems():
        output_header = arduino_src_dir.joinpath('%s.h' % k)
        # Prepend auto-generated warning to generated source code.
        f_get_code = lambda *args_: ((C_GENERATED_WARNING_MESSAGE %
                                      datetime.now()) + f(*(args_ +
                                                            (module_name, ))))

        write_code(input_headers, input_classes, output_header, f_get_code,
                   *['-I%s' % p for p in [lib_dir.abspath()] +
                     c_array_defs.get_includes()],
                   methods_filter=methods_filter)


@task
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_python_code(options):
    from arduino_rpc.code_gen import (write_code,
                                      PYTHON_GENERATED_WARNING_MESSAGE)
    from arduino_rpc.rpc_data_frame import get_python_code
    import c_array_defs

    package_name = options.PROPERTIES['package_name']
    module_name = package_name.replace('-', '_')
    sketch_dir = path(module_name).joinpath('Arduino', module_name)
    lib_dir = base_node_rpc.get_lib_directory()
    output_file = path(module_name).joinpath('node.py')
    input_classes, input_headers = get_base_classes_and_headers(options,
                                                                lib_dir,
                                                                sketch_dir)
    extra_header = ('from base_node_rpc.proxy import ProxyBase, I2cProxyMixin')
    extra_footer = '''

class I2cProxy(I2cProxyMixin, Proxy):
    pass
'''
    # Prepend auto-generated warning to generated source code.
    f_python_code = lambda *args: ((PYTHON_GENERATED_WARNING_MESSAGE %
                                    datetime.now()) +
                                   get_python_code(*args,
                                                   extra_header=extra_header,
                                                   extra_footer=extra_footer))
    methods_filter = getattr(options, 'methods_filter', DEFAULT_METHODS_FILTER)
    write_code(input_headers, input_classes, output_file, f_python_code,
               *['-I%s' % p for p in [lib_dir.abspath()] +
                 c_array_defs.get_includes()], methods_filter=methods_filter)


@task
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_config_c_code(options):
    import nanopb_helpers as npb
    from arduino_rpc.code_gen import C_GENERATED_WARNING_MESSAGE

    sketch_dir = options.rpc_module.get_sketch_directory()
    proto_path = sketch_dir.joinpath('config.proto').abspath()
    options_path = sketch_dir.joinpath('config.options').abspath()

    if proto_path.isfile():
        if options_path.isfile():
            kwargs = {'options_file': options_path}
        else:
            kwargs = {}

        name = options.PROPERTIES['package_name']
        project_lib_dir = verify_library_directory(options)
        arduino_src_dir = project_lib_dir.joinpath('src', project_lib_dir.name)
        if not arduino_src_dir.isdir():
            arduino_src_dir.makedirs_p()

        nano_pb_code = npb.compile_nanopb(proto_path, **kwargs)
        c_output_base = arduino_src_dir.joinpath('config_pb')
        c_header_path = c_output_base + '.h'
        with open(c_output_base + '.c', 'wb') as output:
            print >> output, C_GENERATED_WARNING_MESSAGE % datetime.now()
            output.write(nano_pb_code['source'].replace('{{ header_path }}',
                         c_header_path.name))
        with open(c_header_path, 'wb') as output:
            print >> output, C_GENERATED_WARNING_MESSAGE % datetime.now()
            output.write(nano_pb_code['header']
                         .replace('PB_CONFIG_PB_H_INCLUDED',
                                  'PB__%s__CONFIG_PB_H_INCLUDED' %
                                  name.upper()))


@task
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_config_python_code(options):
    import nanopb_helpers as npb
    from path_helpers import path

    sketch_dir = options.rpc_module.get_sketch_directory()
    proto_path = sketch_dir.joinpath('config.proto').abspath()

    if proto_path.isfile():
        pb_code = npb.compile_pb(proto_path)
        output_path = path(options.PROPERTIES['package_name'].replace('-', '_')).joinpath('config.py')
        output_path.write_bytes(pb_code['python'])


@task
@needs('generate_config_python_code')
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_config_validate_header(options):
    sketch_dir = options.rpc_module.get_sketch_directory()
    generate_validate_header('Config', sketch_dir)


@task
@needs('generate_config_python_code')
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_state_validate_header():
    sketch_dir = options.rpc_module.get_sketch_directory()
    generate_validate_header('State', sketch_dir)


@task
@needs('generate_all_code',
       'arduino_rpc.pavement_base.build_arduino_library')
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def build_arduino_library(options):
    pass


@task
@cmdopts([('overwrite', 'f', 'Force overwrite')])
def init_config():
    '''
    Write basic config protobuf definition to sketch directory
    (`config.proto`).
    '''
    import jinja2
    from . import get_lib_directory

    overwrite = getattr(options, 'overwrite', False)

    sketch_dir = options.rpc_module.get_sketch_directory()
    lib_dir = get_lib_directory()

    output_path = sketch_dir.joinpath('config.proto')
    template = lib_dir.joinpath('config.protot').bytes()

    if not output_path.isfile() or overwrite:
        output = jinja2.Template(template).render(package=
                                                  options.PROPERTIES['package_name'])
        output_path.write_bytes(output)
    else:
        raise IOError('Output path exists.  Use `overwrite` to force '
                      'overwrite.')


@task
@needs('generate_config_c_code', 'generate_config_python_code',
       'generate_config_validate_header', 'generate_state_validate_header',
       'generate_command_processor_header', 'generate_rpc_buffer_header')
@cmdopts([('sconsflags=', 'f', 'Flags to pass to SCons.'),
          ('boards=', 'b', 'Comma-separated list of board names to compile '
           'for (e.g., `uno`).')])
def build_firmware():
    scons_flags = getattr(options, 'sconsflags', '')
    boards = [b.strip() for b in getattr(options, 'boards', '').split(',')
              if b.strip()]
    if not boards:
        boards = options.DEFAULT_ARDUINO_BOARDS
    for board in boards:
        # Compile firmware once for each specified board.
        sh('scons %s ARDUINO_BOARD="%s"' % (scons_flags, board))


@task
@needs('generate_setup', 'minilib', 'build_firmware', 'generate_python_code',
       'setuptools.command.sdist')
def sdist():
    """Overrides sdist to make sure that our setup.py is generated."""
    pass


@task
@needs('generate_setup', 'minilib', 'generate_library_main_header',
       'generate_config_c_code', 'generate_config_python_code',
       'generate_command_processor_header', 'generate_rpc_buffer_header',
       'generate_python_code')
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_all_code(options):
    '''
    Generate all C++ (device) and Python (host) code, but do not compile
    device sketch.
    '''
    pass
