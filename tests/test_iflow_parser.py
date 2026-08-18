from pathlib import Path

from src.models.schema import IFlowArtifact
from src.parser.iflow_parser import parse_package


def test_parse_package_extracts_nodes_edges_and_resources(tmp_path):
    pkg = tmp_path / "demo-package"
    (pkg / "META-INF").mkdir(parents=True)
    (pkg / "src/main/resources/script").mkdir(parents=True)
    (pkg / "src/main/resources/mapping").mkdir(parents=True)
    (pkg / "src/main/resources/xsd").mkdir(parents=True)
    (pkg / "src/main/resources/wsdl").mkdir(parents=True)
    (pkg / "src/main/resources/script").joinpath("script1.groovy").write_text("println 'hi'\n", encoding="utf-8")
    (pkg / "src/main/resources/mapping").joinpath("map1.mmap").write_text("mapping\n", encoding="utf-8")
    (pkg / "src/main/resources/xsd").joinpath("schema1.xsd").write_text("<xsd/>\n", encoding="utf-8")
    (pkg / "src/main/resources/wsdl").joinpath("service.wsdl").write_text("<wsdl/>\n", encoding="utf-8")
    (pkg / "META-INF" / "MANIFEST.MF").write_text(
        "Bundle-SymbolicName: demo.package\nBundle-Version: 1.2.3\n",
        encoding="utf-8",
    )

    iflw_dir = pkg / "src/main/resources/scenarioflows/integrationflow"
    iflw_dir.mkdir(parents=True)
    iflw_file = iflw_dir / "demo.iflw"
    iflw_file.write_text(
        """
        <bpmn2:definitions xmlns:bpmn2="http://www.omg.org/spec/BPMN/20100524/MODEL"
                           xmlns:ifl="http:///com.sap.ifl.model/Ifl.xsd">
          <bpmn2:process id="p1">
            <bpmn2:serviceTask id="task1" name="Load Data">
              <bpmn2:extensionElements>
                <ifl:property>
                  <key>activityType</key>
                  <value>ServiceTask</value>
                </ifl:property>
                <ifl:property>
                  <key>script1</key>
                  <value>script1.groovy</value>
                </ifl:property>
                <ifl:property>
                  <key>resource</key>
                  <value>resourceA</value>
                </ifl:property>
              </bpmn2:extensionElements>
            </bpmn2:serviceTask>
            <bpmn2:callActivity id="task2" name="Transform Map">
              <bpmn2:extensionElements>
                <ifl:property>
                  <key>activityType</key>
                  <value>Mapping</value>
                </ifl:property>
                <ifl:property>
                  <key>mappingName</key>
                  <value>map1.mmap</value>
                </ifl:property>
              </bpmn2:extensionElements>
            </bpmn2:callActivity>
            <bpmn2:sequenceFlow id="sf1" sourceRef="task1" targetRef="task2"/>
          </bpmn2:process>
        </bpmn2:definitions>
        """,
        encoding="utf-8",
    )

    artifact = parse_package(str(pkg))

    assert isinstance(artifact, IFlowArtifact)
    assert artifact.artifact_id == "demo.package"
    assert artifact.version == "1.2.3"
    assert artifact.nodes[0]["id"] == "task1"
    assert artifact.nodes[0]["type"] == "ServiceTask"
    assert artifact.nodes[0]["resources"] == ["script1.groovy", "resourceA"]
    assert artifact.nodes[1]["resources"] == ["map1.mmap"]
    assert artifact.edges == [{"sourceRef": "task1", "targetRef": "task2"}]
    assert artifact.resources["scripts"] == ["script1.groovy"]
    assert artifact.resources["mappings"] == ["map1.mmap"]
    assert artifact.resources["schemas"] == ["schema1.xsd", "service.wsdl"]
    assert artifact.parse_warnings == []


def test_parse_package_extracts_conditions_message_flows_and_systems(tmp_path):
    pkg = tmp_path / "route-package"
    (pkg / "META-INF").mkdir(parents=True)
    (pkg / "src/main/resources/scenarioflows/integrationflow").mkdir(parents=True)
    (pkg / "META-INF" / "MANIFEST.MF").write_text(
        "Bundle-SymbolicName: route-package; singleton:=true\nBundle-Version: 2.0\n",
        encoding="utf-8",
    )

    iflw_file = pkg / "src/main/resources/scenarioflows/integrationflow" / "route.iflw"
    iflw_file.write_text(
        """
        <bpmn2:definitions xmlns:bpmn2="http://www.omg.org/spec/BPMN/20100524/MODEL"
                           xmlns:ifl="http:///com.sap.ifl.model/Ifl.xsd">
          <bpmn2:process id="p1">
            <bpmn2:startEvent id="start" name="Start"/>
            <bpmn2:exclusiveGateway id="gw" name="Router"/>
            <bpmn2:endEvent id="end" name="End"/>
            <bpmn2:sequenceFlow id="sf1" sourceRef="start" targetRef="gw">
              <bpmn2:conditionExpression>${conditionA}</bpmn2:conditionExpression>
            </bpmn2:sequenceFlow>
            <bpmn2:sequenceFlow id="sf2" sourceRef="gw" targetRef="end">
              <bpmn2:extensionElements>
                <ifl:property>
                  <key>conditionExpression</key>
                  <value>Sales Order</value>
                </ifl:property>
              </bpmn2:extensionElements>
            </bpmn2:sequenceFlow>
            <bpmn2:messageFlow id="mf1" sourceRef="sender" targetRef="Receiver_1">
              <bpmn2:extensionElements>
                <ifl:property><key>Direction</key><value>Sender</value></ifl:property>
                <ifl:property><key>ComponentType</key><value>SOAP</value></ifl:property>
                <ifl:property><key>address</key><value>https://example.test</value></ifl:property>
              </bpmn2:extensionElements>
            </bpmn2:messageFlow>
            <bpmn2:participant id="Participant_1" name="S4"/>
            <bpmn2:participant id="Participant_2" name="C4C"/>
          </bpmn2:process>
        </bpmn2:definitions>
        """,
        encoding="utf-8",
    )

    artifact = parse_package(str(pkg))

    assert artifact.artifact_id == "route-package"
    assert artifact.version == "2.0"
    assert artifact.nodes[0]["bpmn_type"] == "startEvent"
    assert artifact.nodes[1]["bpmn_type"] == "exclusiveGateway"
    assert artifact.edges[0]["condition"] == "${conditionA}"
    assert artifact.edges[1]["condition"] == "Sales Order"
    assert artifact.message_flows[0]["direction"] == "Sender"
    assert artifact.message_flows[0]["component_type"] == "SOAP"
    assert artifact.message_flows[0]["address"] == "https://example.test"
    assert artifact.systems == [{"id": "Participant_1", "name": "S4"}, {"id": "Participant_2", "name": "C4C"}]


def test_parse_package_handles_missing_iflw(tmp_path):
    pkg = tmp_path / "empty-package"
    (pkg / "META-INF").mkdir(parents=True)
    (pkg / "META-INF" / "MANIFEST.MF").write_text(
        "Bundle-SymbolicName: missing.iflw\nBundle-Version: 0.0.1\n",
        encoding="utf-8",
    )

    artifact = parse_package(str(pkg))

    assert artifact.artifact_id == "missing.iflw"
    assert artifact.version == "0.0.1"
    assert artifact.nodes == []
    assert artifact.edges == []
    assert artifact.parse_warnings
