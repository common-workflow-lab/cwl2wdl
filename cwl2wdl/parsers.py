"""
Parser classes
"""

from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import warnings
import yaml


class CwlParser(object):
    def __init__(self, cwl, sourceFile):
        self.source = sourceFile
        self.cwl = cwl
        if isinstance(cwl, list):
            self.tasks = [part for part in cwl if part['class'] == 'CommandLineTool']
            self.workflow = [part for part in cwl if part['class'] == 'Workflow']
        elif isinstance(cwl, dict):
            if cwl['class'] == 'CommandLineTool':
                self.tasks = [cwl]
                self.workflow = None
            elif cwl['class'] == 'Workflow':
                self.tasks = None
                self.workflow = cwl
            else:
                warnings.warn("Unrecognized CWL class.")
                self.tasks = None
                self.workflow = None
        else:
            warnings.warn("Unrecognized CWL class.")
            self.tasks = None
            self.workflow = None


class CwlTaskParser(object):
    def __init__(self, cwl_task, sourceFile):
        if 'label' in cwl_task:
            self.name = cwl_task['label']
        else:
            self.name = "_".join(cwl_task['baseCommand'])
        self.baseCommand = cwl_task['baseCommand']
        if 'arguments' in cwl_task:
            if isinstance(cwl_task['arguments'], list):
                if isinstance(cwl_task['arguments'][0], str):
                    self.arguments = cwl_task['arguments']
                else:
                    warnings.warn(
                        "Task arguments of type: %s are not supported" % (type(cwl_task['arguments']))
                    )
                    self.arguments = None
            elif isinstance(cwl_task['arguments'], str):
                self.arguments = [cwl_task['arguments']]
            else:
                self.arguments = None
        else:
            self.arguments = None
        self.inputs = process_cwl_inputs(cwl_task['inputs'])
        self.outputs = process_cwl_outputs(cwl_task['outputs'])
        if 'requirements' in cwl_task:
            self.requirements = process_cwl_requirements(cwl_task['requirements'], sourceFile)
        else:
            self.requirements = [{"requirement_type": None, "value": None}]


class CwlWorkflowParser(object):
    def __init__(self, cwl_workflow):
        if 'label' in cwl_workflow:
            self.name = cwl_workflow['label']
        elif 'id' in cwl_workflow:
            self.name = cwl_workflow['id']
        else:
            raise NameError("This CWL Workflow has no label or id.")
        self.inputs = process_cwl_inputs(cwl_workflow['inputs'])
        self.outputs = process_cwl_outputs(cwl_workflow['outputs'])
        self.steps = process_cwl_workflow_steps(cwl_workflow['steps'])
        if 'requirements' in cwl_workflow:
            self.requirements = process_cwl_requirements(cwl_workflow['requirements'])
        else:
            self.requirements = [{"requirement_type": None, "value": None}]


def remap_type_cwl2wdl(input_type):
    "Remaps CWL types to WDL types. Also determines if variable is required."
    # Map Literals not currently supported
    # Key is CWL type
    # Value is corresponding WDL type
    type_map = {"File": "File",
                "string": "String",
                "boolean": "Boolean",
                "int": "Int",
                "long": "Float",
                "float": "Float",
                "double": "Float",
                "array-File": "Array[File]",
                "array-string": "Array[String]",
                "array-int": "Array[Int]",
                "array-long": "Array[Float]",
                "array-float": "Array[Float]",
                "array-double": "Array[Float]"}

    is_required = False
    if isinstance(input_type, str):
        cwl_type = input_type

    elif isinstance(input_type, list):
        if 'null' in input_type:
            is_required = True
            # keep the first non-null type
            cwl_type = [value for index, value in enumerate(input_type) if value != 'null'][0]
        if isinstance(cwl_type, dict):
            cwl_type = "-".join([cwl_type['type'],
                                 cwl_type['items']])

    elif isinstance(input_type, dict):
        cwl_type = "-".join([input_type['type'],
                             input_type['items']])

    try:
        variable_type = type_map[cwl_type]
        return variable_type, is_required
    except KeyError:
        raise KeyError('Unrecognized CWL type: %s' % (cwl_type))


def process_cwl_inputs(cwl_inputs):
    inputs = []
    for cwl_input in cwl_inputs:
        name = cwl_input['id'].strip("#")

        if 'inputBinding' in cwl_input:
            if 'prefix' in cwl_input['inputBinding']:
                flag = cwl_input['inputBinding']['prefix']
            else:
                flag = None
            if 'position' in cwl_input['inputBinding']:
                position = cwl_input['inputBinding']['position']
            else:
                position = None
            if 'itemSeparator' in cwl_input['inputBinding']:
                separator = cwl_input['inputBinding']['itemSeparator']
            else:
                separator = None
        else:
            flag = None
            position = None
            separator = None

        if 'default' in cwl_input:
            default = cwl_input['default']
        else:
            default = None

        # Types need to be remapped
        variable_type, is_required = remap_type_cwl2wdl(cwl_input['type'])

        parsed_input = {"name": name, "variable_type": variable_type,
                        "is_required": is_required, "flag": flag,
                        "position": position, "separator": separator,
                        "default": default}
        inputs.append(parsed_input)
    return inputs


def process_cwl_outputs(cwl_outputs):
    outputs = []
    for cwl_output in cwl_outputs:
        if 'outputBinding' in cwl_output:
            if 'glob' in cwl_output['outputBinding']:
                if isinstance(cwl_output['outputBinding']['glob'], str):
                    output = 'glob(\'%s\')' % (cwl_output['outputBinding']['glob'])
                else:
                    warnings.warn("Cannot evaluate expression within outputBinding.")
                    output = 'glob(\'%s\')' % (cwl_output['outputBinding']['glob'])
            else:
                warnings.warn("Unsupported outputBinding: %s" % (cwl_output['outputBinding']))
                output = cwl_output['outputBinding']
        elif 'path' in cwl_output:
            output = cwl_output['path']
        else:
            output = None
        name = cwl_output['id'].strip("#")
        # Types must be remapped
        variable_type, is_required = remap_type_cwl2wdl(cwl_output['type'])

        parsed_output = {"name": name,
                         "variable_type": variable_type,
                         "is_required": is_required,
                         "output": output}
        outputs.append(parsed_output)
    return outputs


def process_cwl_requirements(cwl_requirements, sourceFile=None):
    requirements = []
    for cwl_requirement in cwl_requirements:
        # check for docker requirement
        if 'class' in cwl_requirement:
            if cwl_requirement['class'] == 'DockerRequirement':
                requirement_type = "docker"
                if 'dockerImageId' in cwl_requirement:
                    value = cwl_requirement['dockerImageId']
                elif 'dockerPull' in cwl_requirement:
                    value = cwl_requirement['dockerPull']
                else:
                    req_type_err = [key for key in cwl_requirement.keys() if key.startswith("docker")]
                    warnings.warn(
                        "Unsupported docker requirement type: %s" % (" ".join(req_type_err)))
                    continue
            # inline javascript is not supported
            elif cwl_requirement['class'] == 'InlineJavascriptRequirement':
                warnings.warn("This CWL file contains Javascript code."
                              " WDL does not support this feature.")
                continue
            else:
                warnings.warn("The CWL requirement class: %s, is not supported" % (cwl_requirement['class']))
                continue
        elif ('import' in cwl_requirement) or ('$import' in cwl_requirement):
            # warnings.warn("'import' statements are not supported.")
            source_dir = os.path.dirname(os.path.abspath(sourceFile))
            try:
                to_import = cwl_requirement['import']
            except:
                to_import = cwl_requirement['$import']

            if os.path.exists(to_import):
                file_to_import = to_import
            elif os.path.exists(os.path.join(source_dir, to_import)):
                file_to_import = os.path.join(source_dir, to_import)
            else:
                warnings.warn("Couldn't find file: %s" % (to_import))
                continue

            handle = open(file_to_import)
            imported_yaml = yaml.load(handle.read())
            handle.close()

            if isinstance(imported_yaml, list):
                imported_requirements = process_cwl_requirements(imported_yaml)
            else:
                imported_requirements = process_cwl_requirements([imported_yaml])

            requirements += imported_requirements
            continue
        else:
            warnings.warn("The CWL requirement: %s, is not supported" % (cwl_requirement))
            continue

        parsed_requirement = {"requirement_type": requirement_type,
                              "value": value}
        requirements.append(parsed_requirement)

    return requirements


def process_cwl_workflow_steps(workflow_steps):
    steps = []
    for step in workflow_steps:
        task_id = re.sub('(\.cwl|#)', '', step['run']['import'])
        inputs = []
        outputs = None
        parsed_step = {"task_id": task_id,
                       "inputs": inputs,
                       "outputs": outputs}
        steps.append(parsed_step)
    return steps


def expression_converter(expression):
    # TODO
    pass