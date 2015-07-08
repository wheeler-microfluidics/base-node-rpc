from paver.easy import task, needs, path, sh, cmdopts, options
import base_node_rpc


DEFAULT_BASE_CLASSES = ['BaseNodeEeprom', 'BaseNodeI2c', 'BaseNodeSpi']
DEFAULT_METHODS_FILTER = lambda df: df[~(df.method_name
                                         .isin(['get_config_fields',
                                                'get_state_fields']))].copy()


def get_base_classes_and_headers(options, lib_dir, sketch_dir):
    base_classes = getattr(options, 'base_classes', DEFAULT_BASE_CLASSES)
    rpc_classes = getattr(options, 'rpc_classes', ['Node'])
    input_classes = ['BaseNode'] + base_classes + rpc_classes
    input_headers = ([lib_dir.joinpath('BaseNode.h')] +
                     [lib_dir.joinpath('%s.h' % c.split('<')[0])
                      for c in base_classes] +
                     len(rpc_classes) * [sketch_dir.joinpath('Node.h')])
    return input_classes, input_headers


def generate_validate_header(message_name, sketch_dir):
    from importlib import import_module

    from path_helpers import path
    import arduino_array
    from .protobuf import (get_handler_validator_class_code,
                           write_handler_validator_header)
    from . import get_lib_directory

    try:
        config = import_module('.config', package=options.rpc_module.__name__)
    except ImportError:
        return

    lib_dir = get_lib_directory()
    if hasattr(config, message_name):
        package_name = sketch_dir.name
        input_classes, input_headers = get_base_classes_and_headers(options,
                                                                    lib_dir,
                                                                    sketch_dir)
        message_type = getattr(config, message_name)
        args = ['-I%s' % p for p in [lib_dir.abspath()] +
                arduino_array.get_includes()]
        validator_code = get_handler_validator_class_code(input_headers,
                                                          input_classes,
                                                          message_type, *args)

        message_name = message_type.DESCRIPTOR.name.lower()
        output_path = path(sketch_dir).joinpath('%s_%s_validate.h' %
                                                (package_name, message_name))
        write_handler_validator_header(output_path, package_name, message_name,
                                       validator_code)


@task
def generate_rpc_buffer_header():
    import arduino_rpc.rpc_data_frame as rpc_df

    output_dir = (path(options.PROPERTIES['name'])
                  .joinpath('Arduino', options.PROPERTIES['name']))
    rpc_df.generate_rpc_buffer_header(output_dir)


@task
def generate_command_processor_header():
    from arduino_rpc.code_gen import write_code
    from arduino_rpc.rpc_data_frame import get_c_header_code
    import arduino_array

    name = options.PROPERTIES['name']
    sketch_dir = path(name).joinpath('Arduino', name)
    lib_dir = base_node_rpc.get_lib_directory()

    input_classes, input_headers = get_base_classes_and_headers(options,
                                                                lib_dir,
                                                                sketch_dir)
    output_header = path(name).joinpath('Arduino', name,
                                        'NodeCommandProcessor.h')
    extra_header = '\n'.join(['#define BASE_NODE__%s  ("%s")' % (k.upper(), v)
                              for k, v in options.PROPERTIES.iteritems()])
    f_get_code = lambda *args_: get_c_header_code(*(args_ + (name, )),
                                                  extra_header=extra_header)

    methods_filter = getattr(options, 'methods_filter', DEFAULT_METHODS_FILTER)
    write_code(input_headers, input_classes, output_header, f_get_code,
               *['-I%s' % p for p in [lib_dir.abspath()] +
                 arduino_array.get_includes()], methods_filter=methods_filter)


@task
def generate_python_code():
    from arduino_rpc.code_gen import write_code
    from arduino_rpc.rpc_data_frame import get_python_code
    import arduino_array

    name = options.PROPERTIES['name']
    sketch_dir = path(name).joinpath('Arduino', name)
    lib_dir = base_node_rpc.get_lib_directory()
    output_file = path(name).joinpath('node.py')
    input_classes, input_headers = get_base_classes_and_headers(options,
                                                                lib_dir,
                                                                sketch_dir)
    extra_header = ('from base_node_rpc.proxy import ProxyBase, I2cProxyMixin')
    extra_footer = '''

class I2cProxy(I2cProxyMixin, Proxy):
    pass
'''
    f_python_code = lambda *args: get_python_code(*args,
                                                  extra_header=extra_header,
                                                  extra_footer=extra_footer)
    methods_filter = getattr(options, 'methods_filter', DEFAULT_METHODS_FILTER)
    write_code(input_headers, input_classes, output_file, f_python_code,
               *['-I%s' % p for p in [lib_dir.abspath()] +
                 arduino_array.get_includes()], methods_filter=methods_filter)


@task
def generate_config_c_code():
    import nanopb_helpers as npb

    sketch_dir = options.rpc_module.get_sketch_directory()
    proto_path = sketch_dir.joinpath('config.proto').abspath()
    options_path = sketch_dir.joinpath('config.options').abspath()

    if proto_path.isfile():
        if options_path.isfile():
            kwargs = {'options_file': options_path}
        else:
            kwargs = {}
        nano_pb_code = npb.compile_nanopb(proto_path, **kwargs)
        c_output_base = sketch_dir.joinpath(options.PROPERTIES['name'] +
                                            '_config_pb')
        c_header_path = c_output_base + '.h'
        (c_output_base + '.c').write_bytes(nano_pb_code['source']
                                           .replace('{{ header_path }}',
                                                    c_header_path.name))
        c_header_path.write_bytes(nano_pb_code['header'])


@task
def generate_config_python_code():
    import nanopb_helpers as npb
    from path_helpers import path

    sketch_dir = options.rpc_module.get_sketch_directory()
    proto_path = sketch_dir.joinpath('config.proto').abspath()

    if proto_path.isfile():
        pb_code = npb.compile_pb(proto_path)
        output_path = path(options.PROPERTIES['name']).joinpath('config.py')
        output_path.write_bytes(pb_code['python'])


@task
@needs('generate_config_python_code')
def generate_config_validate_header():
    sketch_dir = options.rpc_module.get_sketch_directory()
    generate_validate_header('Config', sketch_dir)


@task
@needs('generate_config_python_code')
def generate_state_validate_header():
    sketch_dir = options.rpc_module.get_sketch_directory()
    generate_validate_header('State', sketch_dir)


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
