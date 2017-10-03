#! /usr/bin/python3
# Copyright Notice:
# Copyright 2017 Distributed Management Task Force, Inc. All rights reserved.
# License: BSD 3-Clause License. For full text see link: https://github.com/DMTF/Redfish-Tools/LICENSE.md

"""
CSDL to JSON Schema

File : csdl-to-json.py

Brief : This file contains the definitions and functionalities for converting
        Redfish CSDL files to Redfish JSON Schema files.
"""

import argparse
import errno
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

# Default configurations
CONFIG_DEF_COPYRIGHT = "Copyright 2014-2017 Distributed Management Task Force, Inc. (DMTF). For the full DMTF copyright policy, see http://www.dmtf.org/about/policies/copyright"
CONFIG_DEF_REDFISH_SCHEMA = "http://redfish.dmtf.org/schemas/v1/redfish-schema.v1_2_0.json"
CONFIG_DEF_ODATA_SCHEMA = "http://redfish.dmtf.org/schemas/v1/odata.4.0.0.json"
CONFIG_DEF_LOCATION = "http://redfish.dmtf.org/schemas/v1/"
CONFIG_DEF_RESOURCE_LOCATION = "http://redfish.dmtf.org/schemas/v1/"

# Regex strings
NAMESPACE_VER_REGEX = "^[a-zA-Z0-9]+\.v([0-9]+)_([0-9]+)_([0-9]+)$"
PATTERN_PROP_REGEX = "^([a-zA-Z_][a-zA-Z0-9_]*)?@(odata|Redfish|Message|Privileges)\\.[a-zA-Z_][a-zA-Z0-9_.]+$"

# OData markup strings
ODATA_TAG_REFERENCE = "{http://docs.oasis-open.org/odata/ns/edmx}Reference"
ODATA_TAG_INCLUDE = "{http://docs.oasis-open.org/odata/ns/edmx}Include"
ODATA_TAG_SCHEMA = "{http://docs.oasis-open.org/odata/ns/edm}Schema"
ODATA_TAG_ENTITY = "{http://docs.oasis-open.org/odata/ns/edm}EntityType"
ODATA_TAG_COMPLEX = "{http://docs.oasis-open.org/odata/ns/edm}ComplexType"
ODATA_TAG_ENUM = "{http://docs.oasis-open.org/odata/ns/edm}EnumType"
ODATA_TAG_ACTION = "{http://docs.oasis-open.org/odata/ns/edm}Action"
ODATA_TAG_TYPE_DEF = "{http://docs.oasis-open.org/odata/ns/edm}TypeDefinition"
ODATA_TAG_ANNOTATION = "{http://docs.oasis-open.org/odata/ns/edm}Annotation"
ODATA_TAG_PROPERTY = "{http://docs.oasis-open.org/odata/ns/edm}Property"
ODATA_TAG_NAV_PROPERTY = "{http://docs.oasis-open.org/odata/ns/edm}NavigationProperty"
ODATA_TAG_MEMBER = "{http://docs.oasis-open.org/odata/ns/edm}Member"
ODATA_TAG_RECORD = "{http://docs.oasis-open.org/odata/ns/edm}Record"
ODATA_TAG_PROP_VAL = "{http://docs.oasis-open.org/odata/ns/edm}PropertyValue"

class CSDLToJSON():
    """
    Class for managing translation data and processing

    Args:
        copyright: The copyright string to use
        redfish_schema: The Redfish JSON Schema file to reference
        odata_schema: The OData JSON Schema file to reference
        location: The output location for the generated schemas
        root: The ET object of the XML file being processed
        resource_root: The ET object of the Resource XML file
    """

    def __init__( self, copyright, redfish_schema, odata_schema, location, root, resource_root ):
        self.copyright = copyright
        self.redfish_schema = redfish_schema
        self.odata_schema = odata_schema
        self.location = location
        self.root = root
        self.resource_root = resource_root
        self.resource_props = []
        self.ref_member_props = []
        self.resource_collection_props = []
        self.links_props = []
        self.cache_resource_definitions()
        self.namespace_under_process = None
        self.external_references = {}
        self.build_external_references()
        self.json_out = {}
        self.initialize_json_output()

    def cache_resource_definitions( self ):
        """
        Processes the Resource XML document to cache core definitions
        """

        # Look for the Resource, ReferenceableMembers, ResourceCollection, and Links definitions
        for schema in self.resource_root.iter( ODATA_TAG_SCHEMA ):
            for child in schema:
                if ( child.tag == ODATA_TAG_ENTITY ) or ( child.tag == ODATA_TAG_COMPLEX ):
                    name = schema.attrib["Namespace"] + "." + child.attrib["Name"]

                    if ( name == "Resource.v1_0_0.Resource" ) or ( name == "Resource.Item" ):
                        for prop in child:
                            if ( prop.tag == ODATA_TAG_PROPERTY ) or ( prop.tag == ODATA_TAG_NAV_PROPERTY ):
                                self.resource_props.append( prop )

                    if ( name == "Resource.v1_0_0.ReferenceableMember" ) or ( name == "Resource.Item" ):
                        for prop in child:
                            if ( prop.tag == ODATA_TAG_PROPERTY ) or ( prop.tag == ODATA_TAG_NAV_PROPERTY ):
                                self.ref_member_props.append( prop )

                    if name == "Resource.v1_0_0.ResourceCollection":
                        for prop in child:
                            if ( prop.tag == ODATA_TAG_PROPERTY ) or ( prop.tag == ODATA_TAG_NAV_PROPERTY ):
                                self.resource_collection_props.append( prop )

                    if name == "Resource.Links":
                        for prop in child:
                            if ( prop.tag == ODATA_TAG_PROPERTY ) or ( prop.tag == ODATA_TAG_NAV_PROPERTY ):
                                self.links_props.append( prop )

    def build_external_references( self ):
        """
        Processes the external references of the XML document
        """

        for reference in self.root.iter( ODATA_TAG_REFERENCE ):
            for include in reference.iter( ODATA_TAG_INCLUDE ):
                # Based on the URI and the namespace, build the expected JSON Schema reference
                self.external_references[include.attrib["Namespace"]] = reference.attrib["Uri"].rsplit( "/", 1 )[0] + "/" + include.attrib["Namespace"] + ".json"

    def initialize_json_output( self ):
        """
        Initializes the output JSON structures for a given XML file
        """

        for schema in self.root.iter( ODATA_TAG_SCHEMA ):
            self.json_out[schema.attrib["Namespace"]] = {}
            self.json_out[schema.attrib["Namespace"]]["$schema"] = self.redfish_schema
            self.json_out[schema.attrib["Namespace"]]["copyright"] = self.copyright
            self.json_out[schema.attrib["Namespace"]]["definitions"] = {}
            self.json_out[schema.attrib["Namespace"]]["title"] = "#" + schema.attrib["Namespace"]

    def process( self ):
        """
        Processes the given data to generate the JSON output
        """

        # Loop on each namespace and build each definition
        for namespace in self.json_out:
            self.namespace_under_process = namespace
            # Process the namespace based on if it's versioned or unversioned
            if is_namespace_unversioned( namespace ):
                self.process_unversioned_namespace()
            else:
                self.process_versioned_namespace()

    def process_unversioned_namespace( self ):
        """
        Adds the definitions to the JSON output for an unversioned namespace
        """

        # Go through each namespace in the XML file
        for schema in self.root.iter( ODATA_TAG_SCHEMA ):
            # Only process the matching namespace
            if schema.attrib["Namespace"] == self.namespace_under_process:
                for child in schema:
                    # Set up the top level title and $ref properties if needed
                    if child.tag == ODATA_TAG_ENTITY:
                        if "BaseType" in child.attrib:
                            if ( child.attrib["BaseType"] == "Resource.v1_0_0.Resource" ) or ( child.attrib["BaseType"] == "Resource.v1_0_0.ResourceCollection" ):
                                self.json_out[self.namespace_under_process]["title"] = self.namespace_under_process + "." + child.attrib["Name"]
                                self.json_out[self.namespace_under_process]["$ref"] = "#/definitions/" + child.attrib["Name"]

                    # Process EntityType and ComplexType definitions
                    if ( child.tag == ODATA_TAG_ENTITY ) or ( child.tag == ODATA_TAG_COMPLEX ):
                        # Check if the definition is abstract
                        is_abstract = False
                        if "Abstract" in child.attrib:
                            if child.attrib["Abstract"] == "true":
                                is_abstract = True
                        if ( child.tag == ODATA_TAG_COMPLEX ) and ( self.namespace_under_process == "Resource" ):
                            # Special override for ComplexType definitions in Resource; we want those to be standalone
                            is_abstract = False
                        if is_abstract:
                            self.generate_abstract_object( child, self.json_out[self.namespace_under_process]["definitions"] )
                        else:
                            self.generate_object( child, self.json_out[self.namespace_under_process]["definitions"] )

                    # Process EnumType definitions if defined in versioned namespaces
                    if child.tag == ODATA_TAG_ENUM:
                        self.generate_enum( child, self.json_out[self.namespace_under_process]["definitions"] )

                    # Process TypeDefinition definitions if the defined in versioned namespaces
                    if child.tag == ODATA_TAG_TYPE_DEF:
                        self.generate_typedef( child, self.json_out[self.namespace_under_process]["definitions"] )

    def process_versioned_namespace( self ):
        """
        Adds the definitions to the JSON output for a versioned namespace
        """

        # Go through each namespace in the XML file
        for schema in self.root.iter( ODATA_TAG_SCHEMA ):
            # Check if the namespace applies based on its version number
            if does_namespace_apply( schema.attrib["Namespace"], self.namespace_under_process ):
                for child in schema:
                    # Set up the top level title and $ref properties if needed
                    if child.tag == ODATA_TAG_ENTITY:
                        if "BaseType" in child.attrib:
                            if ( child.attrib["BaseType"] == "Resource.v1_0_0.Resource" ) or ( child.attrib["BaseType"] == "Resource.v1_0_0.ResourceCollection" ):
                                self.json_out[self.namespace_under_process]["title"] = self.namespace_under_process + "." + child.attrib["Name"]
                                self.json_out[self.namespace_under_process]["$ref"] = "#/definitions/" + child.attrib["Name"]

                    # Process EntityType and ComplexType definitions
                    if ( child.tag == ODATA_TAG_ENTITY ) or ( child.tag == ODATA_TAG_COMPLEX ):
                        if is_namespace_unversioned( schema.attrib["Namespace"] ) == False:
                            self.generate_object( child, self.json_out[self.namespace_under_process]["definitions"] )

                    # Process Action definitions
                    if child.tag == ODATA_TAG_ACTION:
                        self.generate_action( child, self.json_out[self.namespace_under_process]["definitions"] )

                    # Process EnumType definitions if defined in versioned namespaces
                    if child.tag == ODATA_TAG_ENUM:
                        if is_namespace_unversioned( schema.attrib["Namespace"] ) == False:
                            self.generate_enum( child, self.json_out[self.namespace_under_process]["definitions"] )

                    # Process TypeDefinition definitions if the defined in versioned namespaces
                    if child.tag == ODATA_TAG_TYPE_DEF:
                        if is_namespace_unversioned( schema.attrib["Namespace"] ) == False:
                            self.generate_typedef( child, self.json_out[self.namespace_under_process]["definitions"] )

    def generate_abstract_object( self, object, json_def ):
        """
        Processes an abstract EntityType or ComplexType to generate the JSON definition structure

        Args:
            object: The abstract EntityType or ComplexType to process
            json_def: The JSON Definitions body to populate
        """

        name = object.attrib["Name"]

        # The Resource namespace needs to be processed in a special manner since it doesn't follow the Redfish model for object inheritance
        if self.namespace_under_process == "Resource":
            json_def[name] = { "anyOf": [] }

            # Append matching objects in the file to the anyOf list
            for schema in self.root.iter( ODATA_TAG_SCHEMA ):
                namespace = schema.attrib["Namespace"]
                for child in schema:
                    if child.tag == object.tag:
                        if "BaseType" in child.attrib:
                            if child.attrib["BaseType"] == self.namespace_under_process + "." + name:
                                json_def[name]["anyOf"].append( { "$ref": self.location + namespace + ".json#/definitions/" + child.attrib["Name"] } )
        else:
            if object.tag == ODATA_TAG_ENTITY:
                json_def[name] = { "anyOf": [ { "$ref": self.odata_schema + "#/definitions/idRef" } ] }
            else:
                json_def[name] = { "anyOf": [] }

            # Append matching objects in the file to the anyOf list
            for schema in self.root.iter( ODATA_TAG_SCHEMA ):
                namespace = schema.attrib["Namespace"]
                if namespace != self.namespace_under_process:
                    for child in schema:
                        if child.tag == object.tag:
                            if child.attrib["Name"] == name:
                                json_def[name]["anyOf"].append( { "$ref": self.location + namespace + ".json#/definitions/" + name } )

        # Add descriptions
        for child in object:
            if child.tag == ODATA_TAG_ANNOTATION:
                # Object Description
                if child.attrib["Term"] == "OData.Description":
                    json_def[name]["description"] = child.attrib["String"]

                # Object Long Description
                if child.attrib["Term"] == "OData.LongDescription":
                    json_def[name]["longDescription"] = child.attrib["String"]

    def generate_object( self, object, json_def, name = None ):
        """
        Processes an EntityType or ComplexType to generate the JSON definition structure

        Args:
            object: The EntityType or ComplexType to process
            json_def: The JSON Definitions body to populate
            name: The name of the object to populate
        """

        # If the name isn't given, pull it from the object
        if name == None:
            name = object.attrib["Name"]

        # Add the object to the definitions body if this is a new instance
        self.init_object_definition( name, json_def )

        # If this object is an Action, add the predefined title and target properties
        if object.tag == ODATA_TAG_ACTION:
            json_def[name]["properties"]["title"] = { "type": "string", "description": "Friendly action name" }
            json_def[name]["properties"]["target"] = { "type": "string", "format": "uri", "description": "Link to invoke action" }

        # Process the items in the object
        for child in object:
            # Process object level annotations
            if child.tag == ODATA_TAG_ANNOTATION:
                # Object Description
                if ( child.attrib["Term"] == "OData.Description" ) and ( "description" not in json_def[name] ):
                    json_def[name]["description"] = child.attrib["String"]

                # Object Long Description
                if ( child.attrib["Term"] == "OData.LongDescription" ) and ( "longDescription" not in json_def[name] ):
                    json_def[name]["longDescription"] = child.attrib["String"]

                # Additional Properties
                if child.attrib["Term"] == "OData.AdditionalProperties":
                    if "Bool" in child.attrib:
                        if child.attrib["Bool"] == "true":
                            json_def[name]["additionalProperties"] = True
                    else:
                        json_def[name]["additionalProperties"] = True

                # Dynamic Property Patterns
                if child.attrib["Term"] == "Redfish.DynamicPropertyPatterns":
                    # Need to update the pattern properties object based on the records found here
                    for record in child.iter( ODATA_TAG_RECORD ):
                        # Pull out the Pattern and Type of the dynamic property pattern
                        pattern_prop = None
                        type = None
                        for prop_val in record.iter( ODATA_TAG_PROP_VAL ):
                            if prop_val.attrib["Property"] == "Pattern":
                                pattern_prop = prop_val.attrib["String"]
                            if prop_val.attrib["Property"] == "Type":
                                type = prop_val.attrib["String"]

                        # If it's properly defined, add it to the pattern properties for the object
                        if ( pattern_prop != None ) and ( type != None ):
                            json_def[name]["patternProperties"][pattern_prop] = {}
                            json_type, ref, pattern, format = self.csdl_type_to_json_type( type, False )
                            if ref == None:
                                json_def[name]["patternProperties"][pattern_prop]["type"] = json_type
                            else:
                                json_def[name]["patternProperties"][pattern_prop]["$ref"] = ref

            # Process properties and navigation properties
            if ( child.tag == ODATA_TAG_PROPERTY ) or ( child.tag == ODATA_TAG_NAV_PROPERTY ):
                self.generate_property( child, json_def[name] )

        # Add OData specific properties
        self.generate_odata_properties( object, json_def[name] )

        # Add items from the BaseType
        self.generate_object_base( object, name, json_def )

    def generate_object_base( self, object, name, json_def ):
        """
        Processes the BaseType for an EntityType or ComplexType and adds it to the JSON output

        Args:
            object: The EntityType or ComplexType to process
            json_def: The JSON Definitions body to populate
            name: The name of the object to continue extending
        """

        # Check if there is a BaseType
        if "BaseType" not in object.attrib:
            return

        # Check if definitions from Resource need to be mapped
        if object.attrib["BaseType"] == "Resource.v1_0_0.Resource":
            for prop in self.resource_props:
                self.generate_property( prop, json_def[name] )
            return
        elif object.attrib["BaseType"] == "Resource.v1_0_0.ResourceCollection":
            for prop in self.resource_collection_props:
                self.generate_property( prop, json_def[name] )

            # Resource Collections need an additional anyOf layer
            def_copy = json_def[name]
            json_def[name] = { "anyOf": [ { "$ref": self.odata_schema + "#/definitions/idRef" } ] }
            json_def[name]["anyOf"].append( def_copy )
            return
        elif object.attrib["BaseType"] == "Resource.v1_0_0.ReferenceableMember":
            for prop in self.ref_member_props:
                self.generate_property( prop, json_def[name] )
            return
        elif object.attrib["BaseType"] == "Resource.Links":
            for prop in self.links_props:
                self.generate_property( prop, json_def[name] )
            return

        # Loop on the namespaces to find the matching type
        for schema in self.root.iter( ODATA_TAG_SCHEMA ):
            for base_object in schema.iter( object.tag ):
                type_name = schema.attrib["Namespace"] + "." + base_object.attrib["Name"]
                if type_name == object.attrib["BaseType"]:
                    # Match; processs it
                    self.generate_object( base_object, json_def, name )
                    return

    def generate_action( self, action, json_def ):
        """
        Processes an Action and adds it to the JSON output

        Args:
            action: The Action to process
            json_def: The JSON Definitions body to populate
        """

        # Add the object for the Action itself
        self.generate_object( action, json_def )

        # Hook it into the Actions object definition to be one of its properties
        self.init_object_definition( "Actions", json_def )
        action_prop = "#" + self.namespace_under_process.split( "." )[0] + "." + action.attrib["Name"]
        json_def["Actions"]["properties"][action_prop] = { "$ref": "#/definitions/" + action.attrib["Name"] }

    def generate_enum( self, enum, json_def ):
        """
        Processes an EnumType and adds it to the JSON output

        Args:
            enum: The EnumType to process
            json_def: The JSON Definitions body to populate
        """

        # Add the enum to the definitions body if this is a new instance
        # Unlike with objects, we don't check if the enum is already defined; this
        # is because in CSDL, you can't extend enums like you can with objects
        name = enum.attrib["Name"]
        json_def[name] = {}
        json_def[name]["type"] = "string"

        # Process the items in the enum
        for child in enum:
            # Top level annotations
            if child.tag == ODATA_TAG_ANNOTATION:
                # Enum Description
                if child.attrib["Term"] == "OData.Description":
                    json_def[name]["description"] = child.attrib["String"]
                # Enum Long Description
                if child.attrib["Term"] == "OData.LongDescription":
                    json_def[name]["longDescription"] = child.attrib["String"]

            # Enum members
            if child.tag == ODATA_TAG_MEMBER:
                # Add to the enum list
                member_name = child.attrib["Name"]
                if "enum" not in json_def[name]:
                    json_def[name]["enum"] = []
                json_def[name]["enum"].append( member_name )

                # Process the annotations of the current member
                for annotation in child.iter( ODATA_TAG_ANNOTATION ):
                    # Member Description
                    if annotation.attrib["Term"] == "OData.Description":
                        if "enumDescriptions" not in json_def[name]:
                            json_def[name]["enumDescriptions"] = {}
                        json_def[name]["enumDescriptions"][member_name] = annotation.attrib["String"]

                    # Member Long Description
                    if annotation.attrib["Term"] == "OData.LongDescription":
                        if "enumLongDescriptions" not in json_def[name]:
                            json_def[name]["enumLongDescriptions"] = {}
                        json_def[name]["enumLongDescriptions"][member_name] = annotation.attrib["String"]

                    # Member Deprecated
                    if annotation.attrib["Term"] == "Redfish.Deprecated":
                        if "enumDeprecated" not in json_def[name]:
                            json_def[name]["enumDeprecated"] = {}
                        json_def[name]["enumDeprecated"][member_name] = annotation.attrib["String"]

    def generate_typedef( self, typedef, json_def ):
        """
        Processes a TypeDefinition and adds it to the JSON output

        Args:
            typedef: The TypeDefinition to process
            json_def: The JSON Definitions body to populate
        """

        # Check if this is a Redfish Enum
        for child in typedef:
            if child.tag == ODATA_TAG_ANNOTATION:
                if child.attrib["Term"] == "Redfish.Enumeration":
                    # Special handling for Redfish Enums
                    self.generate_redfish_enum( typedef, json_def )
                    return

        # It's not a Redfish Enum; no special handling needed
        name = typedef.attrib["Name"]
        type = typedef.attrib["UnderlyingType"]
        json_def[name] = {}

        # Add the common type info
        self.add_type_info( typedef, type, False, json_def[name] )

    def generate_redfish_enum( self, enum, json_def ):
        """
        Processes a TypeDefinition that contains a Redfish Enum definition

        Args:
            typedef: The Redfish Enum to process
            json_def: The JSON Definitions body to populate
        """

        # Add the enum to the definitions body if this is a new instance
        # Unlike with objects, we don't check if the enum is already defined; this
        # is because in CSDL, you can't extend enums like you can with objects
        name = enum.attrib["Name"]
        json_def[name] = {}
        json_def[name]["type"] = "string"

        # Process the items in the enum
        for child in enum:
            # Only annotations should be at the top level of the definition
            if child.tag == ODATA_TAG_ANNOTATION:
                # Enum Description
                if child.attrib["Term"] == "OData.Description":
                    json_def[name]["description"] = annotation.attrib["String"]

                # Enum Long Description
                if child.attrib["Term"] == "OData.LongDescription":
                    json_def[name]["longDescription"] = annotation.attrib["String"]

                # Enum Members
                if child.attrib["Term"] == "Redfish.Enumeration":
                    # Step into the Redfish Enumeration annotation to pull out the members
                    for record in child.iter( ODATA_TAG_RECORD ):
                        # Get the member name first
                        member_name = None
                        for prop_val in record.iter( ODATA_TAG_PROP_VAL ):
                            if prop_val.attrib["Property"] == "Member":
                                member_name = prop_val.attrib["String"]

                        # If we were successful in getting the member name, add it to the list and process its annotations
                        if member_name != None:
                            # Add the member to the list
                            if "enum" not in json_def[name]:
                                json_def[name]["enum"] = []
                            json_def[name]["enum"].append( member_name )

                            # Add the annotations for the member
                            for rec_annotation in record.iter( ODATA_TAG_ANNOTATION ):
                                # Member Description
                                if rec_annotation.attrib["Term"] == "OData.Description":
                                    if "enumDescriptions" not in json_def[name]:
                                        json_def[name]["enumDescriptions"] = {}
                                    json_def[name]["enumDescriptions"][member_name] = rec_annotation.attrib["String"]

                                # Member Long Description
                                if rec_annotation.attrib["Term"] == "OData.LongDescription":
                                    if "enumLongDescriptions" not in json_def[name]:
                                        json_def[name]["enumLongDescriptions"] = {}
                                    json_def[name]["enumLongDescriptions"][member_name] = rec_annotation.attrib["String"]

                                # Member Deprecated
                                if rec_annotation.attrib["Term"] == "Redfish.Deprecated":
                                    if "enumDeprecated" not in json_def[name]:
                                        json_def[name]["enumDeprecated"] = {}
                                    json_def[name]["enumDeprecated"][member_name] = rec_annotation.attrib["String"]

    def init_object_definition( self, name, json_def ):
        """
        Initializes an object definition

        Args:
            name: The name of the object
            json_def: The JSON Definitions body to populate
        """

        # Only initialize if this is not already defined
        # This is to allow for the fact that a complete object definition is put into each JSON Schema file
        if name not in json_def:
            json_def[name] = {}
            json_def[name]["type"] = "object"
            json_def[name]["additionalProperties"] = False
            json_def[name]["patternProperties"] = {}
            json_def[name]["patternProperties"][PATTERN_PROP_REGEX] = {}
            json_def[name]["patternProperties"][PATTERN_PROP_REGEX]["type"] = [ "array", "boolean", "number", "null", "object", "string" ]
            json_def[name]["patternProperties"][PATTERN_PROP_REGEX]["description"] = "This property shall specify a valid odata or Redfish property."
            json_def[name]["properties"] = {}

    def generate_property( self, property, json_obj_def ):
        """
        Process a Property or NavigationProperty and adds it to the JSON object definition

        Args:
            property: The Property or NavigationProperty to process
            json_obj_def: The JSON object definition to place the property
        """

        # Pull out property info
        prop_name = property.attrib["Name"]
        prop_type = property.attrib["Type"]
        json_obj_def["properties"][prop_name] = {}

        # Determine if this is an array
        is_array = prop_type.startswith( "Collection(" )
        if is_array:
            prop_type = prop_type[11:-1]

        # Add the common type info
        self.add_type_info( property, prop_type, is_array, json_obj_def["properties"][prop_name] )

        # Check for required annotations on the property
        for annotation in property.iter( ODATA_TAG_ANNOTATION ):
            if annotation.attrib["Term"] == "Redfish.Required":
                if "required" not in json_obj_def:
                    json_obj_def["required"] = []
                if prop_name not in json_obj_def["required"]:
                    json_obj_def["required"].append( prop_name )
            if annotation.attrib["Term"] == "Redfish.RequiredOnCreate":
                if "requiredOnCreate" not in json_obj_def:
                    json_obj_def["requiredOnCreate"] = []
                if prop_name not in json_obj_def["requiredOnCreate"]:
                    json_obj_def["requiredOnCreate"].append( prop_name )

        # If this is a collection of navigation properties, add the @odata.count property
        if ( property.tag == ODATA_TAG_NAV_PROPERTY ) and ( is_array == True ):
            json_obj_def["properties"][prop_name + "@odata.count"] = { "$ref": self.odata_schema + "#/definitions/count" }

    def generate_odata_properties( self, object, json_obj_def ):
        """
        Adds OData properties to an object definition if needed

        Args:
            object: The object definition
            json_obj_def: The JSON object definition to place the property
        """

        name = object.attrib["Name"]
        base_type = None
        if "BaseType" in object.attrib:
            base_type = object.attrib["BaseType"]

        # If the object is the Resource, ReferenceableMember, or ResourceCollection object,
        # or is derived from them, then we add the OData properties
        if ( name == "Resource" or
             name == "ReferenceableMember" or
             name == "ResourceCollection" or 
             base_type == "Resource.v1_0_0.Resource" or
             base_type == "Resource.v1_0_0.ReferenceableMember" or
             base_type == "Resource.v1_0_0.ResourceCollection" ):
            json_obj_def["properties"]["@odata.context"] = { "$ref": self.odata_schema + "#/definitions/context" }
            json_obj_def["properties"]["@odata.id"] = { "$ref": self.odata_schema + "#/definitions/id" }
            json_obj_def["properties"]["@odata.type"] = { "$ref": self.odata_schema + "#/definitions/type" }

    def add_type_info( self, type_info, type, is_array, json_type_def ):
        """
        Adds common type information for a given definition

        Args:
            type_info: The structure to process; can be Property, NavigationProperty, or TypeDefinition
            type: The type for the structure
            is_array: Flag if this definition is an array of some sorts
            json_type_def: The JSON object or property definition to populate
        """

        # Determine if this is nullable
        if type_info.tag == ODATA_TAG_TYPE_DEF:
            is_nullable = False
        else:
            is_nullable = True
            if "Nullable" in type_info.attrib:
                if type_info.attrib["Nullable"] == "false":
                    is_nullable = False

        # Convert the type as needed; some types will force a format, pattern, or reference
        json_type, ref, pattern, format = self.csdl_type_to_json_type( type, is_nullable )
        if pattern != None:
            json_type_def["pattern"] = pattern
        if format != None:
            json_type_def["format"] = format

        # Set up the type and reference accordingly
        if is_array:
            json_type_def["type"] = "array"
            if ref == None:
                json_type_def["items"] = { "type": json_type }
            else:
                json_type_def["items"] = { "$ref": ref }
        else:
            if ref == None:
                json_type_def["type"] = json_type
            elif ( is_nullable == False ) and ( ref != None ):
                json_type_def["$ref"] = ref
            else:
                json_type_def["anyOf"] = [ { "$ref": ref }, { "type": "null" } ]

        # Loop through the annotations and add other definitions as needed
        for annotation in type_info.iter( ODATA_TAG_ANNOTATION ):
            # Type Description
            if annotation.attrib["Term"] == "OData.Description":
                json_type_def["description"] = annotation.attrib["String"]

            # Type Long Description
            if annotation.attrib["Term"] == "OData.LongDescription":
                json_type_def["longDescription"] = annotation.attrib["String"]

            # Type Permissions
            if annotation.attrib["Term"] == "OData.Permissions":
                if ( annotation.attrib["EnumMember"] == "OData.Permission/Read" ) or ( annotation.attrib["EnumMember"] == "OData.Permissions/Read" ):
                    json_type_def["readonly"] = True
                else:
                    json_type_def["readonly"] = False

            # Type Format
            if annotation.attrib["Term"] == "OData.IsURL":
                if "Bool" in annotation.attrib:
                    if annotation.attrib["Bool"] == "true":
                        json_type_def["format"] = "uri"
                else:
                    json_type_def["format"] = "uri"

            # Type Units
            if annotation.attrib["Term"] == "Measures.Unit":
                json_type_def["units"] = annotation.attrib["String"]

            # Type Minimum
            if annotation.attrib["Term"] == "Validation.Minimum":
                json_type_def["minimum"] = int( annotation.attrib["Int"] )

            # Type Maximum
            if annotation.attrib["Term"] == "Validation.Maximum":
                json_type_def["maximum"] = int( annotation.attrib["Int"] )

            # Type Pattern
            if annotation.attrib["Term"] == "Validation.Pattern":
                json_type_def["pattern"] = annotation.attrib["String"]

            # Type Deprecated
            if annotation.attrib["Term"] == "Redfish.Deprecated":
                json_type_def["deprecated"] = annotation.attrib["String"]

    def csdl_type_to_json_type( self, type, is_nullable ):
        """
        Converts the CSDL type to a JSON type

        Args:
            type: The CSDL type
            is_nullable: Flag if this type is allowed to be null

        Returns:
            A single or set of basic JSON types this is allowed to be
            A reference to another definition if this can map elsewhere
            The pattern allowed by the type
            The format allowed by the type
        """

        # Initialize locals
        json_type = None
        ref = None
        pattern = None
        format = None

        # Perform the mapping based off the type
        if ( ( type == "Edm.SByte" ) or ( type == "Edm.Int16" ) or ( type == "Edm.Int32" ) or
             ( type == "Edm.Int64" ) or ( type == "Edm.Decimal" ) ):
            if is_nullable:
                json_type = [ "number", "null" ]
            else:
                json_type = "number"
        elif type == "Edm.String":
            if is_nullable:
                json_type = [ "string", "null" ]
            else:
                json_type = "string"
        elif type == "Edm.DateTimeOffset":
            if is_nullable:
                json_type = [ "string", "null" ]
            else:
                json_type = "string"
            format = "date-time"
        elif type == "Edm.Duration":
            if is_nullable:
                json_type = [ "string", "null" ]
            else:
                json_type = "string"
            pattern = "-?P(\d+D)?(T(\d+H)?(\d+M)?(\d+(.\d+)?S)?)?"
        elif type == "Edm.TimeOfDay":
            if is_nullable:
                json_type = [ "string", "null" ]
            else:
                json_type = "string"
            pattern = "([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])(.[0-9]{1,12})?"
        elif type == "Edm.Guid":
            if is_nullable:
                json_type = [ "string", "null" ]
            else:
                json_type = "string"
            pattern = "([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
        elif type == "Edm.Boolean":
            if is_nullable:
                json_type = [ "boolean", "null" ]
            else:
                json_type = "boolean"
        elif ( type == "Edm.PrimitiveType" ) or ( type == "Edm.Primitive" ):
            if is_nullable:
                json_type = [ "string", "boolean", "number", "null" ]
            else:
                json_type = [ "string", "boolean", "number" ]
        else:
            # Does not match the base CSDL types; need to map it via a reference
            namespace_ref = type.rsplit( ".", 1 )[0]
            type_ref = type.split( "." )[-1]
            if namespace_ref in self.external_references:
                ref = self.external_references[namespace_ref] + "#/definitions/" + type_ref
            else:
                # Check if this is a cross reference between versioned and unversioned namespaces
                if is_namespace_unversioned( namespace_ref ) != is_namespace_unversioned( self.namespace_under_process ):
                    # It crosses; they'll be in different files
                    ref = self.location + namespace_ref + ".json#/definitions/" + type_ref
                else:
                    # No crossing; local reference
                    ref = "#/definitions/" + type_ref

        return json_type, ref, pattern, format

def main( argv ):
    """
    Main entry point for the script

    Args:
        argv: Command line arguments from the user
    """

    # Get the input arguments
    argget = argparse.ArgumentParser( description = "A tool used to convert Redfish CSDL files to Redfish JSON Schema files" )
    argget.add_argument( "--input", "-I", type = str, required = True, help = "The folder containing the CSDL files to convert" )
    argget.add_argument( "--output", "-O",  type = str, required = True, help = "The folder to write the converted JSON files" )
    argget.add_argument( "--config", "-C", type = str, help = "The configuration file containing definitions for various links and user strings" )
    args = argget.parse_args()

    # Create the output directory (if needed)
    if not os.path.exists( args.output ):
        os.makedirs( args.output )

    # Read the configuration file
    config_data = {}
    if args.config != None:
        try:
            with open( args.config ) as config_file:
                config_data = json.load( config_file )
        except json.JSONDecodeError:
            print( "ERROR: {} contains a malformed JSON object".format( args.config ) )
            sys.exit( 1 )
        except:
            print( "ERROR: Could not open {}".format( args.config ) )
            sys.exit( 1 )

    # Set up defaults for missing configuration fields
    if "Copyright" not in config_data:
        config_data["Copyright"] = CONFIG_DEF_COPYRIGHT
    if "RedfishSchema" not in config_data:
        config_data["RedfishSchema"] = CONFIG_DEF_REDFISH_SCHEMA
    if "ODataSchema" not in config_data:
        config_data["ODataSchema"] = CONFIG_DEF_ODATA_SCHEMA
    if "Location" not in config_data:
        config_data["Location"] = CONFIG_DEF_LOCATION
    if "ResourceLocation" not in config_data:
        config_data["ResourceLocation"] = CONFIG_DEF_RESOURCE_LOCATION

    # Get the definition for Resource
    resource_file = args.input + os.path.sep + "Resource_v1.xml"
    resource_uri = config_data["ResourceLocation"] + "Resource_v1.xml"
    if os.path.isfile( resource_file ):
        # Local copy of Resource; use it
        try:
            resource_tree = ET.parse( resource_file )
            resource_root = resource_tree.getroot()
        except ET.ParseError:
            print( "ERROR: {} contains a malformed XML document".format( resource_file ) )
            sys.exit( 1 )
        except:
            print( "ERROR: Could not open {}".format( resource_file ) )
            sys.exit( 1 )
    else:
        # Fall back on using the remote copy of Resource
        retry_count = 0
        retry_count_max = 20
        while retry_count < retry_count_max:
            try:
                req = urllib.request.Request( resource_uri )
                response = urllib.request.urlopen( req )
                resource_data = response.read()
                resource_root = ET.fromstring( resource_data )
                break
            except Exception as e:
                if e.errno != errno.ECONNRESET:
                    print( "Could not open " + resource_uri )
                    print( e )
                    sys.exit( 1 )
                retry_count += 1
            if retry_count >= retry_count_max:
                print( "Could not open " + resource_uri )
                print( "Too many connection resets" )
                sys.exit( 1 )

    # Step through each file in the input directory
    for filename in os.listdir( args.input ):
        if filename.endswith( ".xml" ):
            print( "Generating JSON for: {}".format( filename ) )
            root = None
            try:
                tree = ET.parse( args.input + os.path.sep + filename )
                root = tree.getroot()
            except ET.ParseError:
                print( "ERROR: {} contains a malformed XML document".format( filename ) )
            except:
                print( "ERROR: Could not open {}".format( filename ) )
            if root != None:
                # Translate and write the JSON files
                translator = CSDLToJSON( config_data["Copyright"], config_data["RedfishSchema"], config_data["ODataSchema"], config_data["Location"], root, resource_root )
                translator.process()
                for namespace in translator.json_out:
                    filename = args.output + os.path.sep + namespace + ".json"
                    out_string = json.dumps( translator.json_out[namespace], sort_keys = True, indent = 4, separators = ( ",", ": " ) )
                    with open( filename, "w" ) as file:
                        file.write( out_string )

def is_namespace_unversioned( namespace ):
    """
    Checks if a namespace is unversioned

    Args:
        namespace: The string name of the namespace

    Returns:
        True if the namespace is unversioned, False otherwise
    """

    # Versioned namespaces match the form NAME.vX_Y_Z
    if re.match( NAMESPACE_VER_REGEX, namespace ) == None:
        return True
    return False

def does_namespace_apply( namespace, json_file_version ):
    """
    Checks if a namespace applies to a given JSON file version

    Args:
        namespace: The string name of the namespace
        json_file_version: The string for the JSON file and its version

    Returns:
        True if the namespace applies, False otherwise
    """

    # If the base name of the namespaces do not match, then it does not apply
    # Currently the only case this happens is in RedfishExtensions_v1.xml
    if namespace.split( "." )[0] != json_file_version.split( "." )[0]:
        return False

    # Unversioned namespaces always apply
    if is_namespace_unversioned( namespace ):
        return True

    # Pull out the version numbers
    namespace_ver = get_namespace_version( namespace )
    json_ver = get_namespace_version( json_file_version )

    # Different major versions; not compatible
    if namespace_ver[0] != json_ver[0]:
        return False

    # The namespace has a newer minor version; skip
    if namespace_ver[1] > json_ver[1]:
        return False

    # The minor versions are equal, but the namespace has a newer errata version; skip
    if ( namespace_ver[1] == json_ver[1] ) and ( namespace_ver[2] > json_ver[2] ):
        return False

    return True

def get_namespace_version( namespace ):
    """
    Pulls the version numbers from a namespace string

    Args:
        namespace: The string name of the namespace

    Returns:
        The major version
        The minor version
        The errata version
    """

    groups = re.match( NAMESPACE_VER_REGEX, namespace )
    return groups.group( 1 ), groups.group( 2 ), groups.group( 3 )

if __name__ == '__main__':
    sys.exit( main( sys.argv ) )
