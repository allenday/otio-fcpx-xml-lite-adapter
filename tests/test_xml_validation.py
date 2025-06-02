# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

import unittest
import xml.etree.ElementTree as ET
from xml.dom import minidom
import opentimelineio as otio
from opentimelineio import opentime
import opentimelineio.test_utils as otio_test_utils
from otio_fcpx_xml_lite_adapter.writer import FcpXmlWriter
import os
import subprocess
import tempfile


class XMLValidationTest(unittest.TestCase, otio_test_utils.OTIOAssertions):
    """Test XML validation against FCPXML DTD to prevent specification violations"""
    
    def setUp(self):
        self.dtd_path = os.path.join(os.path.dirname(__file__), 'dtds', 'fcpxml-1.13.dtd')
        self.maxDiff = None
    
    def _validate_xml_against_dtd(self, xml_content):
        """Validate XML content against FCPXML DTD using xmllint"""
        try:
            # Create temporary files for XML and DTD
            with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as xml_file:
                xml_file.write(xml_content)
                xml_file_path = xml_file.name
            
            # Validate using xmllint
            result = subprocess.run([
                'xmllint', '--noout', '--dtdvalid', self.dtd_path, xml_file_path
            ], capture_output=True, text=True)
            
            # Clean up
            os.unlink(xml_file_path)
            
            if result.returncode != 0:
                self.fail(f"XML validation failed against DTD:\n{result.stderr}")
            
            return True
            
        except FileNotFoundError:
            self.skipTest("xmllint not available - install libxml2-utils for XML validation")
        except Exception as e:
            self.fail(f"XML validation error: {e}")
    
    def _create_basic_timeline(self):
        """Create a basic timeline for testing"""
        timeline = otio.schema.Timeline(name="Test Timeline")
        timeline.global_start_time = otio.opentime.RationalTime(0, 25)
        
        # Add video track
        video_track = otio.schema.Track(name="Video Track", kind=otio.schema.TrackKind.Video)
        timeline.tracks.append(video_track)
        
        # Add a simple clip
        clip_ref = otio.schema.ExternalReference(
            target_url="file:///path/to/test.mov"
        )
        
        clip = otio.schema.Clip(
            name="Test Clip",
            media_reference=clip_ref,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, 25),
                duration=otio.opentime.RationalTime(100, 25)
            )
        )
        
        video_track.append(clip)
        return timeline
    
    def test_basic_timeline_validates_against_dtd(self):
        """Test that a basic timeline generates valid FCPXML according to DTD"""
        timeline = self._create_basic_timeline()
        
        # Generate FCPXML
        writer = FcpXmlWriter(timeline)
        xml_content = writer.build_xml_string()
        
        # Validate against DTD
        self._validate_xml_against_dtd(xml_content)
    
    def test_timeline_with_different_frame_rates_validates(self):
        """Test that timelines with different frame rates still generate valid FCPXML"""
        timeline = otio.schema.Timeline(name="Mixed Frame Rate Timeline")
        timeline.global_start_time = otio.opentime.RationalTime(0, 24)
        
        # Add video track
        video_track = otio.schema.Track(name="Video Track", kind=otio.schema.TrackKind.Video)
        timeline.tracks.append(video_track)
        
        # Add clip with 24fps
        clip_ref_24 = otio.schema.ExternalReference(target_url="file:///path/to/24fps.mov")
        clip_24 = otio.schema.Clip(
            name="24fps Clip",
            media_reference=clip_ref_24,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, 24),
                duration=otio.opentime.RationalTime(96, 24)
            )
        )
        video_track.append(clip_24)
        
        # Add clip with 30fps
        clip_ref_30 = otio.schema.ExternalReference(target_url="file:///path/to/30fps.mov")
        clip_30 = otio.schema.Clip(
            name="30fps Clip", 
            media_reference=clip_ref_30,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, 30),
                duration=otio.opentime.RationalTime(120, 30)
            )
        )
        video_track.append(clip_30)
        
        # Generate and validate FCPXML
        writer = FcpXmlWriter(timeline)
        xml_content = writer.build_xml_string()
        self._validate_xml_against_dtd(xml_content)
    
    def test_audio_track_validates_against_dtd(self):
        """Test that audio tracks generate valid FCPXML"""
        timeline = otio.schema.Timeline(name="Audio Timeline")
        timeline.global_start_time = otio.opentime.RationalTime(0, 48000)
        
        # Add audio track
        audio_track = otio.schema.Track(name="Audio Track", kind=otio.schema.TrackKind.Audio)
        timeline.tracks.append(audio_track)
        
        # Add audio clip
        audio_ref = otio.schema.ExternalReference(target_url="file:///path/to/audio.wav")
        audio_clip = otio.schema.Clip(
            name="Audio Clip",
            media_reference=audio_ref,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, 48000),
                duration=otio.opentime.RationalTime(48000, 48000)
            )
        )
        audio_track.append(audio_clip)
        
        # Generate and validate FCPXML
        writer = FcpXmlWriter(timeline)
        xml_content = writer.build_xml_string()
        self._validate_xml_against_dtd(xml_content)
    
    def test_complex_timeline_validates_against_dtd(self):
        """Test that a complex timeline with multiple tracks validates"""
        timeline = otio.schema.Timeline(name="Complex Timeline")
        timeline.global_start_time = otio.opentime.RationalTime(0, 25)
        
        # Add video track
        video_track = otio.schema.Track(name="Video Track", kind=otio.schema.TrackKind.Video)
        timeline.tracks.append(video_track)
        
        # Add audio track
        audio_track = otio.schema.Track(name="Audio Track", kind=otio.schema.TrackKind.Audio) 
        timeline.tracks.append(audio_track)
        
        # Add multiple clips to video track
        for i in range(3):
            clip_ref = otio.schema.ExternalReference(
                target_url=f"file:///path/to/video_{i}.mov"
            )
            clip = otio.schema.Clip(
                name=f"Video Clip {i}",
                media_reference=clip_ref,
                source_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(i * 50, 25),
                    duration=otio.opentime.RationalTime(50, 25)
                )
            )
            video_track.append(clip)
        
        # Add multiple clips to audio track
        for i in range(3):
            audio_ref = otio.schema.ExternalReference(
                target_url=f"file:///path/to/audio_{i}.wav"
            )
            audio_clip = otio.schema.Clip(
                name=f"Audio Clip {i}",
                media_reference=audio_ref,
                source_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(i * 1250, 25),
                    duration=otio.opentime.RationalTime(1250, 25)
                )
            )
            audio_track.append(audio_clip)
        
        # Generate and validate FCPXML
        writer = FcpXmlWriter(timeline)
        xml_content = writer.build_xml_string()
        self._validate_xml_against_dtd(xml_content)
    
    def test_invalid_attributes_would_fail_validation(self):
        """Test that invalid attributes like frameDuration on asset-clip would fail DTD validation"""
        # This test demonstrates what would happen if we incorrectly added frameDuration 
        # to asset-clip elements (which we fixed earlier)
        
        timeline = self._create_basic_timeline()
        writer = FcpXmlWriter(timeline)
        xml_content = writer.build_xml_string()
        
        # Manually inject an invalid frameDuration attribute to asset-clip 
        # (this should fail validation)
        invalid_xml = xml_content.replace(
            '<asset-clip',
            '<asset-clip frameDuration="1/25s"'
        )
        
        # This should fail DTD validation
        try:
            self._validate_xml_against_dtd(invalid_xml)
            self.fail("Expected DTD validation to fail with invalid frameDuration attribute on asset-clip")
        except AssertionError as e:
            # This is expected - the test should fail DTD validation
            if "XML validation failed against DTD" in str(e):
                pass  # This is what we expect
            else:
                raise  # Re-raise if it's a different assertion error
    
    def test_well_formed_xml_structure(self):
        """Test that generated XML is well-formed"""
        timeline = self._create_basic_timeline()
        writer = FcpXmlWriter(timeline)
        xml_content = writer.build_xml_string()
        
        # Test that XML can be parsed without errors
        try:
            root = ET.fromstring(xml_content)
            self.assertEqual(root.tag, 'fcpxml')
            self.assertEqual(root.get('version'), '1.13')
        except ET.ParseError as e:
            self.fail(f"Generated XML is not well-formed: {e}")
    
    def test_dtd_file_exists_and_is_readable(self):
        """Test that the DTD file exists and is readable"""
        self.assertTrue(os.path.exists(self.dtd_path), f"DTD file not found at {self.dtd_path}")
        
        # Test that DTD content looks reasonable
        with open(self.dtd_path, 'r') as f:
            dtd_content = f.read()
            self.assertIn('<!ELEMENT fcpxml', dtd_content)
            self.assertIn('<!ELEMENT asset-clip', dtd_content)
            self.assertIn('<!ELEMENT format', dtd_content)
            
            # Ensure frameDuration is NOT allowed on asset-clip
            # (this is the key validation we want to enforce)
            lines = dtd_content.split('\n')
            asset_clip_attrs = []
            in_asset_clip_attrs = False
            
            for line in lines:
                if '<!ATTLIST asset-clip' in line:
                    in_asset_clip_attrs = True
                elif in_asset_clip_attrs and line.strip().startswith('<!'):
                    break
                elif in_asset_clip_attrs:
                    asset_clip_attrs.append(line.strip())
            
            asset_clip_attrs_str = ' '.join(asset_clip_attrs)
            self.assertNotIn('frameDuration', asset_clip_attrs_str, 
                           "frameDuration should not be allowed on asset-clip elements")


if __name__ == '__main__':
    unittest.main() 