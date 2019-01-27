# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from knack.log import get_logger

from azure.cli.core._help import (HelpExample, CliHelpFile)
import abc

logger = get_logger(__name__)

try:
    ABC = abc.ABC
except AttributeError:  # Python 2.7, abc exists, but not ABC
    ABC = abc.ABCMeta('ABC', (object,), {'__slots__': ()})


# BaseHelpLoader defining versioned loader interface. Also contains some helper methods.
class BaseHelpLoader(ABC):
    def __init__(self, help_ctx=None):
        self.help_ctx = help_ctx
        self._data = None

    def versioned_load(self, help_obj, parser):
        self.load_raw_data(help_obj, parser)
        if self._data_is_applicable():
            self.load_help_body(help_obj)
            self.load_help_parameters(help_obj)
            self.load_help_examples(help_obj)

    @property
    @abc.abstractmethod
    def version(self):
        pass

    def _data_is_applicable(self):
        is_applicable = False
        ldr_name = self.__class__
        if self._data:
            is_applicable = self.version == self._data.get('version')
            msg = "Data's version matches loader {}'s version.".format(ldr_name) if is_applicable \
                else "Data's version: {} does not match loader {}'s version: {}".format(self._data.get('version'),
                                                                                        ldr_name, self.version)
            logger.info(msg)
        else:
            logger.info("There is no applicable data for loader {}.".format(ldr_name))

        return is_applicable

    @abc.abstractmethod
    def load_raw_data(self, help_obj, parser):
        pass

    @abc.abstractmethod
    def load_help_body(self, help_obj):
        pass

    @abc.abstractmethod
    def load_help_parameters(self, help_obj):
        pass

    @abc.abstractmethod
    def load_help_examples(self, help_obj):
        pass

    # Loader static helper methods

    # Update a help file object from a data dict using the attribute to key mapping
    @staticmethod
    def _update_obj_from_data_dict(obj, data, attr_key_tups):
        for attr, key in attr_key_tups:
            try:
                setattr(obj, attr, data[key] or attr)
            except (AttributeError, KeyError):
                pass

    # update relevant help file object parameters from data.
    @staticmethod
    def _update_help_obj_params(help_obj, data_params, params_equal, attr_key_tups):
        loaded_params = []
        for param_obj in help_obj.parameters:
            loaded_param = next((n for n in data_params if params_equal(param_obj, n)), None)
            if loaded_param:
                BaseHelpLoader._update_obj_from_data_dict(param_obj, loaded_param, attr_key_tups)
            loaded_params.append(param_obj)
        help_obj.parameters = loaded_params

    # get the yaml help
    @staticmethod
    def _get_yaml_help_for_nouns(nouns, cmd_loader_map_ref, cmd_group_table):
        import inspect
        import os

        def _parse_yaml_from_string(text, help_file_path):
            import yaml

            dir_name, base_name = os.path.split(help_file_path)

            pretty_file_path = os.path.join(os.path.basename(dir_name), base_name)

            try:
                data = yaml.load(text)
                if not data:
                    raise CLIError("Error: Help file {} is empty".format(pretty_file_path))
                return data
            except yaml.YAMLError as e:
                raise CLIError("Error parsing {}:\n\n{}".format(pretty_file_path, e))

        command_nouns = " ".join(nouns)
        # if command in map, get the loader. Path of loader is path of helpfile.
        loader = cmd_loader_map_ref.get(command_nouns, [None])[0]

        # otherwise likely a group, try to find command loader through command group object.
        if not loader:
            for grp_name, grp_obj in cmd_group_table.items():
                # Note, some groups such as 'az sf' do not have azcommandgroup objects ("with self.command_group()")
                if grp_obj and grp_name == command_nouns:
                    loader = grp_obj.command_loader
                    break

        # if couldn't find group object in cmd_group_table, try using command loader object through command prefix.
        if not loader:
            for cmd_name, cmd_ldr in cmd_loader_map_ref.items():
                # if first word in loader name is the group, this is a command in the command group
                if cmd_name.startswith(command_nouns + " "):
                    loader = cmd_ldr[0]
                    break

        if loader:
            loader_file_path = inspect.getfile(loader.__class__)
            dir_name = os.path.dirname(loader_file_path)
            files = os.listdir(dir_name)
            for file in files:
                if file.endswith("help.yaml") or file.endswith("help.yml"):
                    help_file_path = os.path.join(dir_name, file)
                    with open(help_file_path, "r") as f:
                        text = f.read()
                        return _parse_yaml_from_string(text, help_file_path)
        return None


class HelpLoaderV0(BaseHelpLoader):

    @property
    def version(self):
        return 0

    def versioned_load(self, help_obj, parser):
        super(CliHelpFile, help_obj).load(parser)

    def load_raw_data(self, help_obj, parser):
        pass

    def load_help_body(self, help_obj):
        pass

    def load_help_parameters(self, help_obj):
        pass

    def load_help_examples(self, help_obj):
        pass


class HelpLoaderV1(BaseHelpLoader):
    core_attrs_to_keys = [("short_summary", "summary"), ("long_summary", "description")]
    body_attrs_to_keys = core_attrs_to_keys + [("links", "links")]
    param_attrs_to_keys = core_attrs_to_keys + [("value_sources", "value-sources")]

    @property
    def version(self):
        return 1

    def load_raw_data(self, help_obj, parser):
        prog = parser.prog if hasattr(parser, "prog") else parser._prog_prefix
        command_nouns = prog.split()[1:]
        cmd_loader_map_ref = self.help_ctx.cli_ctx.invocation.commands_loader.cmd_to_loader_map
        cmd_group_tbl = self.help_ctx.cli_ctx.invocation.commands_loader.command_group_table
        all_data = self._get_yaml_help_for_nouns(command_nouns, cmd_loader_map_ref, cmd_group_tbl)
        self._data = self._get_entry_data(help_obj.command, all_data)

    def load_help_body(self, help_obj):
        help_obj.long_summary = "" # TEMPORARY TO MIMIC KNACK behavior
        self._update_obj_from_data_dict(help_obj, self._data, self.body_attrs_to_keys)

    def load_help_parameters(self, help_obj):
        def params_equal(param, param_dict):
            if param_dict['name'].startswith("--"):  # for optionals, help file name must be one of the  long options
                return param_dict['name'] in param.name.split()
            else:  # for positionals, help file must name must match param name shown when -h is run
                return param_dict['name'] == param.name

        if help_obj.type == "command" and hasattr(help_obj, "parameters") and self._data.get("arguments"):
            loaded_params = []
            for param_obj in help_obj.parameters:
                loaded_param = next((n for n in self._data["arguments"] if params_equal(param_obj, n)), None)
                if loaded_param:
                    self._update_obj_from_data_dict(param_obj, loaded_param, self.param_attrs_to_keys)
                loaded_params.append(param_obj)
            help_obj.parameters = loaded_params

    def load_help_examples(self, help_obj):
        if help_obj.type == "command" and self._data.get("examples"):
            help_obj.examples = [HelpExample(**ex) for ex in self._data["examples"] if help_obj._should_include_example(ex)]

    @staticmethod
    def _get_entry_data(cmd_name, data):
        if data and data.get("content"):
            try:
                entry_data = next(value for elem in data.get("content") for key, value in elem.items() if value.get("name") == cmd_name)
                entry_data["version"] = data['version']
                return entry_data
            except StopIteration:
                pass
        return None
