# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

import unittest
import xml.etree.ElementTree as ET
import opentimelineio as otio
from opentimelineio import opentime
import opentimelineio.test_utils as otio_test_utils
from otio_fcpx_xml_lite_adapter.writer import FcpXmlWriter
from fractions import Fraction


class PerAssetFrameRateTest(unittest.TestCase, otio_test_utils.OTIOAssertions):
    """Test per-asset frame rate support in FCPXML export"""

    def test_per_asset_frame_rates(self):
        """Test that each asset gets its own frameDuration based on source_range.rate"""
        
        # Create timeline with 25fps
        timeline = otio.schema.Timeline(name="Mixed Frame Rate Timeline")
        timeline.global_start_time = otio.opentime.RationalTime(0, 25)
        
        # Add video track
        video_track = otio.schema.Track(name="Video Track", kind=otio.schema.TrackKind.Video)
        timeline.tracks.append(video_track)
        
        # Create clips with different source frame rates
        
        # Clip 1: 24fps source
        clip1_ref = otio.schema.ExternalReference(
            target_url="file:///path/to/clip1.mov",
            available_range=opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, 24),
                duration=otio.opentime.RationalTime(48, 24)  # 2 seconds at 24fps
            )
        )
        clip1 = otio.schema.Clip(
            name="24fps Clip",
            media_reference=clip1_ref,
            source_range=opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, 24),
                duration=otio.opentime.RationalTime(48, 24)  # 2 seconds at 24fps
            )
        )
        
        # Clip 2: 30fps source  
        clip2_ref = otio.schema.ExternalReference(
            target_url="file:///path/to/clip2.mov",
            available_range=opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, 30),
                duration=otio.opentime.RationalTime(60, 30)  # 2 seconds at 30fps
            )
        )
        clip2 = otio.schema.Clip(
            name="30fps Clip", 
            media_reference=clip2_ref,
            source_range=opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, 30),
                duration=otio.opentime.RationalTime(60, 30)  # 2 seconds at 30fps
            )
        )
        
        # Add clips to track
        video_track.append(clip1)
        video_track.append(clip2)
        
        # Generate FCPXML
        writer = FcpXmlWriter(timeline)
        fcpxml_string = writer.build_xml_string()
        
        # Parse the generated XML
        root = ET.fromstring(fcpxml_string)
        
        # Find the sequence and verify it uses timeline frame rate (25fps)
        sequence = root.find('.//sequence')
        self.assertIsNotNone(sequence)
        sequence_format_id = sequence.get('format')
        self.assertIsNotNone(sequence_format_id)
        
        # Find the sequence format and verify its frame rate
        sequence_format = root.find(f'.//format[@id="{sequence_format_id}"]')
        self.assertIsNotNone(sequence_format)
        self.assertEqual(sequence_format.get('frameDuration'), '1/25s')
        
        # Find asset-clip elements
        asset_clips = root.findall('.//asset-clip')
        self.assertEqual(len(asset_clips), 2)
        
        # Verify each asset-clip has the correct frameDuration
        clip1_asset_clip = None
        clip2_asset_clip = None
        
        for asset_clip in asset_clips:
            if asset_clip.get('name') == '24fps Clip':
                clip1_asset_clip = asset_clip
            elif asset_clip.get('name') == '30fps Clip':
                clip2_asset_clip = asset_clip
        
        self.assertIsNotNone(clip1_asset_clip, "24fps clip not found")
        self.assertIsNotNone(clip2_asset_clip, "30fps clip not found")
        
        # With the new feature, each asset-clip should have its own frameDuration
        self.assertEqual(clip1_asset_clip.get('frameDuration'), '1/24s', 
                        "24fps clip should have frameDuration='1/24s'")
        self.assertEqual(clip2_asset_clip.get('frameDuration'), '1/30s',
                        "30fps clip should have frameDuration='1/30s'")

    def test_fractional_frame_rates(self):
        """Test that fractional frame rates like 29.97 fps are handled correctly"""
        
        # Create timeline with 25fps
        timeline = otio.schema.Timeline(name="Fractional Frame Rate Timeline")
        timeline.global_start_time = otio.opentime.RationalTime(0, 25)
        
        # Add video track
        video_track = otio.schema.Track(name="Video Track", kind=otio.schema.TrackKind.Video)
        timeline.tracks.append(video_track)
        
        # Create clip with 29.97 fps (NTSC)
        # 29.97 fps is represented as 30000/1001 in exact form
        rate_2997 = Fraction(30000, 1001)  # This creates the exact 29.97 rate
        
        clip_ref = otio.schema.ExternalReference(
            target_url="file:///path/to/ntsc_clip.mov",
            available_range=opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, rate_2997),
                duration=otio.opentime.RationalTime(60, rate_2997)  # 2 seconds at 29.97fps
            )
        )
        clip = otio.schema.Clip(
            name="29.97fps Clip",
            media_reference=clip_ref,
            source_range=opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, rate_2997),
                duration=otio.opentime.RationalTime(60, rate_2997)  # 2 seconds at 29.97fps
            )
        )
        
        video_track.append(clip)
        
        # Generate FCPXML
        writer = FcpXmlWriter(timeline)
        fcpxml_string = writer.build_xml_string()
        
        # Parse the generated XML
        root = ET.fromstring(fcpxml_string)
        
        # Find the asset-clip element
        asset_clip = root.find('.//asset-clip')
        self.assertIsNotNone(asset_clip)
        
        # Verify the frameDuration is correct for 29.97 fps
        # 29.97 fps = 30000/1001 fps, so frameDuration should be 1001/30000s
        frame_duration = asset_clip.get('frameDuration')
        self.assertEqual(frame_duration, '1001/30000s', 
                        "29.97fps clip should have frameDuration='1001/30000s'")


if __name__ == '__main__':
    unittest.main() 