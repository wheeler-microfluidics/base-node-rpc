from __future__ import absolute_import
from __future__ import print_function
from datetime import datetime
import os
import platform
import sys
import warnings

from paver.easy import task, needs, path, sh, cmdopts, options, consume_args
import base_node_rpc
import path_helpers as ph
import platformio_helpers as pioh
import platformio_helpers.develop
import six
try:
    from arduino_rpc.pavement_base import *
except ImportError:
    # Ignore import error to allow import during installation of
    # `base-node-rpc` (i.e., prior to the installation of `arduino-rpc` through
    # install dependencies).
    LIB_CMDOPTS = None
    LIB_GENERATE_TASKS = None


DEFAULT_BASE_CLASSES = ['BaseNodeSerialHandler', 'BaseNodeEeprom',
                        'BaseNodeI2c', 'BaseNodeI2cHandler<Handler>',
                        'BaseNodeSpi']
DEFAULT_METHODS_FILTER = lambda df: df[~(df.method_name
                                         .isin(['get_config_fields',
                                                'get_state_fields']))].copy()
DEFAULT_POINTER_BITWIDTH = 16
prefix = 'base_node_rpc.pavement_base.'


def _get_module_name(properties):
    if 'module_name' in properties:
        return properties['module_name']
    else:
        return properties['package_name'].replace('-', '_')


def get_base_classes_and_headers(options, lib_dir, sketch_dir):
    '''
    Return ordered list of classes to scan for method discovery, along with a
    corresponding list of the header file where each class may be found.

     - Base classes refer to classes that are to be found in the
       `base-node-rpc` library directory.
     - rpc classes refer to classes found in the sketch directory.
    '''
    from . import get_lib_directory

    module_name = _get_module_name(options.PROPERTIES)
    base_classes = getattr(options, 'base_classes', DEFAULT_BASE_CLASSES)
    rpc_classes = getattr(options, 'rpc_classes', [module_name + '::Node'])

    input_classes = ['BaseNode'] + base_classes + rpc_classes

    # Assume `base-node-rpc` has already been installed as a Conda package.
    base_node_lib_dir = (pioh.conda_arduino_include_path()
                         .joinpath('BaseNodeRpc', 'src', 'BaseNodeRpc'))
    if not base_node_lib_dir.isdir():
        # Library directory not found in Conda include paths since
        # `base-node-rpc` has **not** been installed as a Conda package.
        #
        # Assume running code from source directory.
        base_node_lib_dir = get_lib_directory().joinpath('BaseNodeRpc', 'src',
                                                         'BaseNodeRpc')
    input_headers = ([base_node_lib_dir.joinpath('BaseNode.h')] +
                     [base_node_lib_dir.joinpath('%s.h' % c.split('<')[0])
                      for c in base_classes] +
                     len(rpc_classes) * [sketch_dir.joinpath('Node.h')])
    return input_classes, input_headers


def generate_validate_header(py_proto_module_name, sketch_dir):
    '''
    If package has a Protocol Buffer message class type with the specified
    message name defined, scan node base classes for callback methods related to
    the message type.

    For example, if the message name is `Config`, callbacks of the form
    `on_config_<field name>_changed` will be matched.

    The following callback signatures are supported:

        bool on_config_<field name>_changed()
        bool on_config_<field name>_changed(new_value)
        bool on_config_<field name>_changed(current_value, new_value)

    The corresponding field in Protocol Buffer message will be set to the new
    value *only* if the callback returns `true`.
    '''
    from importlib import import_module

    from clang_helpers.data_frame import underscore_to_camelcase
    from path_helpers import path
    from .protobuf import (get_handler_validator_class_code,
                           write_handler_validator_header)
    from . import get_lib_directory

    c_protobuf_struct_name = underscore_to_camelcase(py_proto_module_name)

    try:
        mod = import_module('.' + py_proto_module_name,
                            package=options.rpc_module.__name__)
    except ImportError:
        warnings.warn('ImportError: could not import %s.%s' %
                      options.rpc_module.__name__, mod_name)
        return

    lib_dir = get_lib_directory()
    if hasattr(mod, c_protobuf_struct_name):
        module_name = _get_module_name(options.PROPERTIES)
        input_classes, input_headers = get_base_classes_and_headers(options,
                                                                    lib_dir,
                                                                    sketch_dir)

        message_type = getattr(mod, c_protobuf_struct_name)

        # Add stub `stdint.h` header to includes path.
        stdint_stub_path = (ph.path(__file__).parent.joinpath('StdIntStub')
                            .realpath())
        c_array_defs_path = (pioh.conda_arduino_include_path()
                             .joinpath('CArrayDefs'))
        args = ['-DSTDINT_STUB']
        include_paths = [stdint_stub_path, lib_dir.realpath(),
                         c_array_defs_path]
        args += ['-I%s' % p for p in include_paths]

        validator_code = get_handler_validator_class_code(input_headers,
                                                          input_classes,
                                                          message_type, *args)

        output_path = path(sketch_dir).joinpath('%s_%s_validate.h' %
                                                (module_name,
                                                 c_protobuf_struct_name
                                                 .lower()))
        write_handler_validator_header(output_path, module_name,
                                       c_protobuf_struct_name.lower(),
                                       validator_code)


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
    import jinja2

    module_name = _get_module_name(options.PROPERTIES)
    sketch_dir = options.rpc_module.get_sketch_directory()
    lib_dir = base_node_rpc.get_lib_directory()

    input_classes, input_headers = get_base_classes_and_headers(options,
                                                                lib_dir,
                                                                sketch_dir)
    camel_name = underscore_to_camelcase(module_name)

    project_lib_dir = verify_library_directory(options)
    arduino_src_dir = project_lib_dir.joinpath('src', project_lib_dir.name)
    if not arduino_src_dir.isdir():
        arduino_src_dir.makedirs_p()

    with arduino_src_dir.joinpath('Properties.h').open('w') as output:
        print(C_GENERATED_WARNING_MESSAGE % datetime.now(), file=output)
        print('#ifndef ___%s__PROPERTIES___' % module_name.upper(), file=output)
        print('#define ___%s__PROPERTIES___' % module_name.upper(), file=output)
        print('', file=output)
        for k, v in six.iteritems(options.PROPERTIES):
            print('#ifndef BASE_NODE__%s' % k.upper(), file=output)
            print('#define BASE_NODE__%s  ("%s")' % (k.upper(), v), file=output)
            print('#endif', file=output)
        print('', file=output)
        print('#endif', file=output)

    with sketch_dir.joinpath('NodeCommandProcessor.h').open('w') as output:
        template = jinja2.Template('''\
#ifndef ___{{ name.upper()  }}___
#define ___{{ name.upper()  }}___

#include "{{ camel_name }}/Properties.h"
#include "{{ camel_name }}/CommandProcessor.h"

#endif  // #ifndef ___{{ name.upper()  }}___''')
        print(C_GENERATED_WARNING_MESSAGE % datetime.now(), file=output)
        print(template.render(name=module_name, camel_name=camel_name),
              file=output)
        print('', file=output)

    headers = {'Commands': get_c_commands_header_code,
               'CommandProcessor': get_c_command_processor_header_code}

    methods_filter = getattr(options, 'methods_filter', DEFAULT_METHODS_FILTER)
    pointer_width = getattr(options, 'pointer_width', DEFAULT_POINTER_BITWIDTH)

    for k, f in six.iteritems(headers):
        output_header = arduino_src_dir.joinpath('%s.h' % k)
        # Prepend auto-generated warning to generated source code.
        f_get_code = lambda *args_: ((C_GENERATED_WARNING_MESSAGE %
                                      datetime.now()) +
                                     f(*(args_ + (module_name, )),
                                       pointer_width=pointer_width))

        # Add stub `stdint.h` header to includes path.
        stdint_stub_path = (ph.path(__file__).parent.joinpath('StdIntStub')
                            .realpath())
        c_array_defs_path = (pioh.conda_arduino_include_path()
                             .joinpath('CArrayDefs'))
        args = ['-DSTDINT_STUB']
        include_paths = [stdint_stub_path, lib_dir.realpath(),
                         c_array_defs_path]
        args += ['-I%s' % p for p in include_paths]
        write_code(input_headers, input_classes, output_header, f_get_code,
                   *args, methods_filter=methods_filter,
                   pointer_width=pointer_width)


@task
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_python_code(options):
    from arduino_rpc.code_gen import (write_code,
                                      PYTHON_GENERATED_WARNING_MESSAGE)
    from arduino_rpc.rpc_data_frame import get_python_code

    module_name = _get_module_name(options.PROPERTIES)
    sketch_dir = options.rpc_module.get_sketch_directory()
    lib_dir = base_node_rpc.get_lib_directory()
    output_file = path(module_name).joinpath('node.py')
    input_classes, input_headers = get_base_classes_and_headers(options,
                                                                lib_dir,
                                                                sketch_dir)
    extra_header = ('from base_node_rpc.proxy import ProxyBase, '
                    'I2cProxyMixin, SerialProxyMixin')
    extra_footer = '''

class I2cProxy(I2cProxyMixin, Proxy):
    pass


class SerialProxy(SerialProxyMixin, Proxy):
    pass
'''
    # Prepend auto-generated warning to generated source code.
    f_python_code = lambda *args: ((PYTHON_GENERATED_WARNING_MESSAGE %
                                    datetime.now()) +
                                   get_python_code(*args,
                                                   extra_header=extra_header,
                                                   extra_footer=extra_footer,
                                                   pointer_width=
                                                   pointer_width))
    methods_filter = getattr(options, 'methods_filter', DEFAULT_METHODS_FILTER)
    pointer_width = getattr(options, 'pointer_width', DEFAULT_POINTER_BITWIDTH)

    # Add stub `stdint.h` header to includes path.
    stdint_stub_path = (ph.path(__file__).parent.joinpath('StdIntStub')
                        .realpath())
    c_array_defs_path = (pioh.conda_arduino_include_path()
                         .joinpath('CArrayDefs'))
    args = ['-DSTDINT_STUB']
    include_paths = [stdint_stub_path, lib_dir.realpath(), c_array_defs_path]
    args += ['-I%s' % p for p in include_paths]
    write_code(input_headers, input_classes, output_file, f_python_code,
               *args, methods_filter=methods_filter,
               pointer_width=pointer_width)


@task
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_protobuf_c_code(options):
    '''
    For each Protocol Buffer definition (i.e., `*.proto`) in the sketch
    directory, use the nano protocol buffer compiler to generate C code for the
    corresponding protobuf message structure(s).
    '''
    import nanopb_helpers as npb
    from arduino_rpc.code_gen import C_GENERATED_WARNING_MESSAGE

    sketch_dir = options.rpc_module.get_sketch_directory()
    for proto_path in sketch_dir.abspath().files('*.proto'):
        proto_name = proto_path.namebase
        options_path = proto_path.parent.joinpath(proto_name +
                                                  '.options')
        if options_path.isfile():
            kwargs = {'options_file': options_path}
        else:
            kwargs = {}

        module_name = _get_module_name(options.PROPERTIES)
        project_lib_dir = verify_library_directory(options)
        arduino_src_dir = project_lib_dir.joinpath('src', project_lib_dir.name)
        if not arduino_src_dir.isdir():
            arduino_src_dir.makedirs_p()

        nano_pb_code = npb.compile_nanopb(proto_path, **kwargs)
        c_output_base = arduino_src_dir.joinpath(proto_name + '_pb')
        c_header_path = c_output_base + '.h'
        with open(c_output_base + '.c', 'w') as output:
            print(C_GENERATED_WARNING_MESSAGE % datetime.now(), file=output)
            output.write(nano_pb_code['source'].replace('{{ header_path }}',
                                                        c_header_path.name))
        with open(c_header_path, 'w') as output:
            print(C_GENERATED_WARNING_MESSAGE % datetime.now(), file=output)
            output.write(nano_pb_code['header']
                         .replace('PB_%s_PB_H_INCLUDED' % proto_name.upper(),
                                  'PB__%s__%s_PB_H_INCLUDED' %
                                  (module_name.upper(), proto_name.upper())))


@task
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_protobuf_python_code(options):
    import nanopb_helpers as npb
    from path_helpers import path

    sketch_dir = options.rpc_module.get_sketch_directory()
    for proto_path in sketch_dir.abspath().files('*.proto'):
        proto_name = proto_path.namebase
        pb_code = npb.compile_pb(proto_path)
        module_name = _get_module_name(options.PROPERTIES)
        output_path = path(module_name).joinpath(proto_name + '.py')
        output_path.write_text(pb_code['python'])


@task
@needs('generate_protobuf_python_code')
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_validate_headers(options):
    '''
    For each Protocol Buffer definition (i.e., `*.proto`) in the sketch
    directory, generate code to call corresponding validation methods (if any)
    present on the `Node` class.

    See `generate_validate_header` for more information.
    '''
    sketch_dir = options.rpc_module.get_sketch_directory()
    for proto_path in sketch_dir.abspath().files('*.proto'):
        proto_name = proto_path.namebase
        print('[generate_validate_headers] Generate validation header for %s'
              % proto_name)
        generate_validate_header(proto_name, sketch_dir)


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
    template = lib_dir.joinpath('config.protot').text()

    if not output_path.isfile() or overwrite:
        output = jinja2.Template(template).render(package=
                                                  options
                                                  .PROPERTIES['package_name'])
        output_path.write_text(output)
    else:
        raise IOError('Output path exists.  Use `overwrite` to force '
                      'overwrite.')


@task
@needs('build_arduino_library', 'build_firmware', 'generate_setup', 'minilib',
       'setuptools.command.sdist')
def sdist():
    """Overrides sdist to make sure that our setup.py is generated."""
    pass

@task
@needs('build_arduino_library', 'build_firmware', 'generate_setup', 'minilib',
       'setuptools.command.bdist_wheel')
def bdist_wheel():
    """Overrides bdist_wheel to make sure that our setup.py is generated."""
    pass


@task
@needs('generate_library_main_header', 'generate_protobuf_c_code',
       'generate_protobuf_python_code', 'generate_validate_headers',
       'generate_command_processor_header', 'generate_rpc_buffer_header',
       'generate_python_code')
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_all_code(options):
    '''
    Generate all C++ (device) and Python (host) code, but do not compile
    device sketch.
    '''
    pass


@task
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def generate_library_main_header(options):
    '''
    Generate an (empty) header file which may be included in the Arduino sketch
    to trigger inclusion of the rest of the library.
    '''
    package_name = options.PROPERTIES['package_name']
    module_name = package_name.replace('-', '_')

    library_dir = verify_library_directory(options)
    library_header = library_dir.joinpath('src', '%s.h' % library_dir.name)
    if not library_header.isdir():
        library_header.parent.makedirs_p()
    with library_header.open('w') as output:
        output.write('''
#ifndef ___{module_name_upper}__H___
#define ___{module_name_upper}__H___

#endif  // #ifndef ___{module_name_upper}__H___
    '''.strip().format(module_name_upper=module_name.upper()))



@task
@needs('setuptools.command.install')
def install(options):
    """Override install to copy Arduino library to sketch library directory."""
    pass


@task
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def develop_link(options):
    import logging; logging.basicConfig(level=logging.INFO)

    pioh.develop.link(working_dir=path('.').realpath(),
                      package_name=options.package_name)


@task
@cmdopts(LIB_CMDOPTS, share_with=LIB_GENERATE_TASKS)
def develop_unlink(options):
    import logging; logging.basicConfig(level=logging.INFO)

    pioh.develop.unlink(working_dir=path('.').realpath(),
                        package_name=options.package_name)


@task
@needs('generate_all_code')
def build_firmware():
    sh('pio run')


@task
@consume_args
def upload(args):
    sh(['pio', 'run', '--target', 'upload', '--target', 'nobuild'] +
       (list(args) if args else []))
