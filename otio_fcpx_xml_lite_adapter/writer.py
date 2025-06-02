# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

import opentimelineio as otio
import xml.etree.ElementTree as ET
import xml.dom.minidom
import os
import re
from fractions import Fraction

# Import helper from adapter (adjust path if needed)
# from .adapter import _fcpx_time_str
# Import from utils instead
from otio_fcpx_xml_lite_adapter.utils import _fcpx_time_str

import logging
logger = logging.getLogger(__name__)

class FcpXmlWriter:
    """Handles the conversion of an OTIO Timeline to an FCPXML string."""

    def __init__(self, input_otio: otio.schema.Timeline):
        if not isinstance(input_otio, otio.schema.Timeline):
            raise otio.exceptions.OTIOError(
                f"Input must be an otio.schema.Timeline, not {type(input_otio)}"
            )

        self.timeline = input_otio
        logger.info("Initializing FcpXmlWriter")

        # Basic structure setup - following DTD: fcpxml > project > (resources, sequence)
        self.version = self.timeline.metadata.get('fcpx_version', '1.13') # Use stored version or default
        self.root = ET.Element("fcpxml", version="1.13")
        
        # DTD structure: project contains resources and sequence
        project_name = self.timeline.name or "OTIO Project"
        self.project = ET.SubElement(self.root, "project", name=project_name)
        self.resources = ET.SubElement(self.project, "resources")

        # Resource Management State
        self.resource_map_assets = {}
        self.resource_map_formats = {}
        self.resource_map_effects = {}
        self.asset_elements = {}
        self.format_elements = {}
        self.effect_elements = {}
        self.next_resource_id_num = 1

        # Timing and Structure State
        self.global_start_time = self.timeline.global_start_time
        if self.global_start_time is None:
            raise otio.exceptions.OTIOError(
                "Timeline.global_start_time is required but is None. "
                "Please set timeline.global_start_time to specify the project frame rate. "
                "Example: timeline.global_start_time = otio.opentime.RationalTime(0, 25)  # for 25fps"
            )
        self.global_rate = self.global_start_time.rate
        self.timeline_duration = self.timeline.duration()
        self.seq_duration_str = _fcpx_time_str(self.timeline_duration)

        # Sequence and Spine elements (initialized after format is ensured)
        self.sequence = None
        self.spine = None
        self.main_container_gap = None

        # Lane Mapping State
        self.track_lane_map = {}
        self.primary_track_lane = None # Lane number (e.g., 1) designated primary

        # Initial Setup Calls
        self._ensure_sequence_format()
        self._create_sequence_element()
        self._map_tracks_to_lanes()
        self._create_main_container_gap()

    def _ensure_resource(self, key, map_dict, element_dict, element_generator):
        """Gets or creates a resource ID and its corresponding XML element."""
        if key not in map_dict:
            # Complex matching for effects (simplification here)
            existing_id = None
            if element_generator.__name__ == '_create_effect_element':
                ref_id, name, uid = key
                for res_id, elem in element_dict.items():
                    if uid and elem.get('uid') == uid: existing_id = res_id; break
                    if name and elem.get('name') == name: existing_id = res_id; break
                if existing_id:
                    map_dict[key] = existing_id
                    map_dict[ref_id] = existing_id
                    return existing_id

            # Create new ID if not found or not an effect
            new_id = f"r{self.next_resource_id_num}"
            self.next_resource_id_num += 1
            map_dict[key] = new_id
            if element_generator.__name__ == '_create_effect_element':
                 map_dict[ref_id] = new_id # Map raw ref_id too
            element_generator(new_id, key)
            return new_id
        return map_dict[key]

    def _create_sequence_format(self, fmt_id, rate_key):
        """Generates the <format> element for the sequence."""
        rate_num, rate_den = rate_key.as_integer_ratio()
        frame_dur_frac = Fraction(rate_den, rate_num).limit_denominator()
        frame_dur_str = f"{frame_dur_frac.numerator}/{frame_dur_frac.denominator}s" if frame_dur_frac.denominator != 1 else f"{frame_dur_frac.numerator}s"
        # DTD only allows: id, name, frameDuration, fieldOrder, width, height, paspH, paspV
        fmt = ET.Element("format", id=fmt_id, name=f"FFVideoFormat_OTIO_{int(rate_key)}",
                             frameDuration=frame_dur_str, width="1920", height="1080") # TODO: Get resolution?
        self.format_elements[fmt_id] = fmt

    def _ensure_sequence_format(self):
        """Ensures the sequence format resource is created."""
        logger.info("Ensuring sequence format.")
        self.sequence_format_id = self._ensure_resource(
            self.global_rate,
            self.resource_map_formats,
            self.format_elements,
            self._create_sequence_format
        )

    def _create_sequence_element(self):
        """Creates the main <sequence> element."""
        logger.info("Creating sequence element.")
        logger.debug(f"OTIO Timeline Duration: {self.timeline_duration} ({self.timeline_duration.value / self.timeline_duration.rate:.3f}s)")
        logger.debug(f"Calculated sequence duration attribute: {self.seq_duration_str}")
        self.sequence = ET.SubElement(self.project, "sequence",
                                     format=self.sequence_format_id,
                                     duration=self.seq_duration_str,
                                     tcStart=_fcpx_time_str(self.global_start_time),
                                     tcFormat="NDF", # Assume NDF
                                     audioLayout="stereo",
                                     audioRate="48k") # Defaults

    def _map_tracks_to_lanes(self):
        """Determines FCPXML lane mapping for OTIO tracks."""
        logger.info("Mapping tracks to lanes.")
        video_lane_counter = 1
        audio_lane_counter = -1
        potential_primary_track = None

        # First pass: Assign initial lanes and find first video track
        temp_lane_map = {}
        for track in self.timeline.tracks:
            if track.kind == otio.schema.TrackKind.Video:
                if potential_primary_track is None:
                     potential_primary_track = track # First video track is candidate
                temp_lane_map[track] = video_lane_counter
                video_lane_counter += 1
            elif track.kind == otio.schema.TrackKind.Audio:
                temp_lane_map[track] = audio_lane_counter
                audio_lane_counter -= 1
            # Ignore other track kinds

        # Second pass: Finalize lanes, ensuring primary is lane 1 if possible
        self.track_lane_map = {}
        video_lane_counter = 1
        audio_lane_counter = -1
        primary_assigned = False

        for track in self.timeline.tracks:
             if track.kind == otio.schema.TrackKind.Video:
                 lane_num = 1 if track == potential_primary_track else video_lane_counter
                 if lane_num == 1:
                      if primary_assigned: # Lane 1 already taken, bump this track
                           lane_num = 2
                           if video_lane_counter == 1: video_lane_counter = 2 # Ensure counter skips 1 next time
                      else:
                           self.primary_track_lane = lane_num # Assign lane 1 as primary
                           primary_assigned = True
                 self.track_lane_map[track] = lane_num
                 if lane_num >= video_lane_counter: video_lane_counter = lane_num + 1

             elif track.kind == otio.schema.TrackKind.Audio:
                 self.track_lane_map[track] = audio_lane_counter
                 audio_lane_counter -= 1

        if not primary_assigned:
             logger.warning("No primary video track identified or assigned lane 1.")


    def _create_main_container_gap(self):
        """Creates the main container <gap> inside the <spine>."""
        logger.info("Creating main container gap.")
        self.spine = ET.SubElement(self.sequence, "spine")
        self.main_container_gap = ET.SubElement(self.spine, "gap",
                                           name="Timeline Container",
                                           offset="0s",
                                           duration=self.seq_duration_str,
                                           start="0s")

    # --- Element Creation Helpers --- #

    def _create_asset_element(self, asset_id, url_key):
        """Creates an <asset> element and adds it to self.asset_elements."""
        # Note: This relies on the context available when _ensure_resource called it.
        # We need access to the item/track info to determine hasAudio/hasVideo etc.
        # This suggests asset creation might need more context or happen closer to item processing.
        # For now, let's recreate the minimal logic from ensure_resource context.
        # TODO: Refactor this to pass necessary context (item, track) or create assets differently.

        # Minimal info - this needs improvement as it lacks context from the clip/track
        media_ref = None # Need a way to get the media_ref here
        item_duration = self.timeline_duration # Fallback
        track_kind = otio.schema.TrackKind.Video # Fallback
        # We cannot reliably get media_ref.available_range or track.kind here easily.
        # This highlights a limitation of creating the resource detached from its usage.

        asset_duration_rt = item_duration # Use timeline duration as fallback
        asset_start_rt = otio.opentime.RationalTime(0, self.global_rate)
        asset_duration_str = _fcpx_time_str(asset_duration_rt)
        asset_start_str = _fcpx_time_str(asset_start_rt)
        has_audio = "1" if track_kind == otio.schema.TrackKind.Audio else "0" # FAKE
        has_video = "1" if track_kind == otio.schema.TrackKind.Video else "0" # FAKE
        
        # DTD requires src attribute directly on asset, not nested media-rep
        asset = ET.Element("asset", 
                          id=asset_id, 
                          name=os.path.basename(url_key) or f"Asset_{asset_id}",
                          src=url_key,  # DTD: src is required attribute on asset
                          start=asset_start_str, 
                          duration=asset_duration_str,
                          hasAudio=has_audio, 
                          hasVideo=has_video,
                          audioRate="48k", 
                          audioChannels="2") # Defaults
        
        # Removed media-rep creation - not valid per DTD
        self.asset_elements[asset_id] = asset
        logger.debug(f"[Created minimal asset resource: {asset_id} (Needs context improvement)")

    def _create_effect_element(self, effect_res_id, key):
        """Creates an <effect> element and adds it to self.effect_elements."""
        ref_id, name, uid = key
        attrs = {"id": effect_res_id}
        attrs["name"] = name or "Placeholder Effect"
        attrs["uid"] = uid # Set the UID

        # *** Removed effectType addition as it's not valid in FCPXML 1.9 ***

        effect_elem = ET.Element("effect", **attrs)
        self.effect_elements[effect_res_id] = effect_elem
        # Use the simpler print statement again
        logger.debug(f"Generated effect resource: id={effect_res_id} name={attrs['name']} uid={attrs['uid']}")

    def _add_markers_to_element(self, item_elem, otio_item):
        """Adds <marker> elements to a clip/gap element based on OTIO markers."""
        if not hasattr(otio_item, 'markers') or not otio_item.markers:
            return

        logger.debug(f"Adding markers for item: {otio_item.name}")
        # Calculate the start time of the item within its parent context
        # For Clips, use trimmed_range().start_time relative to the track start
        # For Gaps or others (like the container gap), assume start at 0 relative to parent
        # This might need adjustment if adding markers directly to sequences/tracks
        if isinstance(otio_item, otio.schema.Clip) and hasattr(otio_item, 'trimmed_range'):
             item_start_time = otio_item.trimmed_range().start_time
        elif isinstance(otio_item, otio.schema.Gap):
            # If it's the main container gap, its effective start is 0
            # If it's an inner gap, its start is relative to its position in the track
            # For simplicity here, assume gaps processed by this func are relative to 0
             item_start_time = otio_item.source_range.start_time # Use Gap's source_range start
        else:
             # Fallback for items without a clear source_range/trimmed_range (e.g., Track?)
             logger.warning(f"Item '{otio_item.name}' type {type(otio_item)} lacks standard range for marker offset calculation. Assuming relative to 0.")
             item_start_time = otio.opentime.RationalTime(0, self.global_rate)


        for marker in otio_item.markers:
             try:
                 # Calculate marker start time relative to the item's start time determined above
                 marker_start_offset = marker.marked_range.start_time - item_start_time

                 # Ensure marker offset isn't negative (marker starts before the item it's attached to)
                 if marker_start_offset < otio.opentime.RationalTime(0, self.global_rate):
                     logger.warning(f"Marker '{marker.name}' start time {marker.marked_range.start_time} is before calculated item start {item_start_time}. Clamping offset to 0.")
                     marker_start_offset = otio.opentime.RationalTime(0, self.global_rate)

                 marker_start_str = _fcpx_time_str(marker_start_offset)

                 # FCPXML marker duration is typically 1 frame for point markers
                 marker_duration_rt = otio.opentime.RationalTime(1, self.global_rate)
                 marker_duration_str = _fcpx_time_str(marker_duration_rt)

                 marker_attrs = {
                     "start": marker_start_str,
                     "duration": marker_duration_str,
                     "value": marker.name,  # Keep value for potential compatibility/debugging
                     "note": marker.name    # *** Use note for the primary marker text ***
                 }

                 # Add completed attribute for 'To Do' (red) markers
                 # Use 'downbeat' in name (case-insensitive) to signify a 'To Do' marker (red)
                 if marker.name and "downbeat" in marker.name.lower():
                     marker_attrs["completed"] = "0" # 0 for To Do (Red), 1 for Standard (Blue)
                 # Add Chapter marker configuration if name contains 'chapter' (case-insensitive)
                 elif marker.name and "chapter" in marker.name.lower():
                      marker_attrs["configuration"] = "chapter" # FCPXML 1.9+ way for Chapter markers

                 ET.SubElement(item_elem, "marker", attrib=marker_attrs)

             except Exception as e:
                 logger.error(f"Error processing marker '{marker.name}' on item '{otio_item.name}': {e}")

    def _create_asset_clip_element(self, item, track, lane, is_primary):
        """Creates an <asset-clip> element for an OTIO Clip with ExternalReference."""
        media_ref = item.media_reference
        if not (isinstance(media_ref, otio.schema.ExternalReference) and media_ref.target_url):
            return None

        media_url = media_ref.target_url
        item_start_time_in_timeline = item.trimmed_range_in_parent().start_time
        item_duration = item.trimmed_range().duration

        # Define nested asset creation function to capture context
        def _create_asset_with_context(asset_id, url_key):
            asset_duration_rt = media_ref.available_range.duration if media_ref.available_range else item_duration
            asset_start_rt = media_ref.available_range.start_time if media_ref.available_range else otio.opentime.RationalTime(0, item_duration.rate)
            asset_duration_str = _fcpx_time_str(asset_duration_rt)
            asset_start_str = _fcpx_time_str(asset_start_rt)
            has_audio = "1" if track.kind == otio.schema.TrackKind.Audio else "0"
            has_video = "1" if track.kind == otio.schema.TrackKind.Video else "0"
            # DTD requires src attribute directly on asset, not nested media-rep
            asset = ET.Element("asset", 
                              id=asset_id, 
                              name=os.path.basename(url_key) or f"Asset_{asset_id}",
                              src=url_key,  # DTD: src is required attribute on asset
                              start=asset_start_str, 
                              duration=asset_duration_str,
                              hasAudio=has_audio, 
                              hasVideo=has_video,
                              audioRate="48k", 
                              audioChannels="2") # Defaults
            # Removed media-rep creation - not valid per DTD
            self.asset_elements[asset_id] = asset
            logger.debug(f"Created asset resource: {asset_id}")

        # Ensure asset exists, creating it with context if needed
        asset_id = self._ensure_resource(media_url, self.resource_map_assets, self.asset_elements, _create_asset_with_context)

        clip_elem_attrs = {
            "name": item.name or f"Clip_{asset_id}",
            "ref": asset_id,
            "offset": _fcpx_time_str(item_start_time_in_timeline),
            "duration": _fcpx_time_str(item_duration),
            "start": _fcpx_time_str(item.source_range.start_time)
        }
        
        # Asset clips always get lane attribute in container gap structure
        clip_elem_attrs["lane"] = str(lane)
        logger.debug(f"Adding Lane Attr (Container): {lane}")

        # Handle enabled attribute - only add if explicitly disabled
        if hasattr(item, 'enabled') and item.enabled is False:
            clip_elem_attrs["enabled"] = "0"

        item_elem = ET.Element("asset-clip", **clip_elem_attrs)

        if track.kind == otio.schema.TrackKind.Audio:
            item_elem.set("role", "dialogue")  # DTD specifies "role", not "audioRole"

        self._add_markers_to_element(item_elem, item)
        return item_elem

    def _create_generator_element(self, item, track, lane, is_primary, media_ref):
        """Creates a <title> or <video> element for an OTIO Clip with GeneratorReference."""
        item_start_time_in_timeline = item.trimmed_range_in_parent().start_time
        item_duration = item.trimmed_range().duration
        item_elem = None

        fcpx_ref = media_ref.parameters.get('fcpx_ref')
        effect_name = media_ref.parameters.get('fcpx_effect_name')
        effect_uid = media_ref.parameters.get('fcpx_effect_uid')
        effect_res_id = None

        if fcpx_ref:
            effect_key = (fcpx_ref, effect_name, effect_uid)
            effect_res_id = self._ensure_resource(effect_key, self.resource_map_effects, self.effect_elements, self._create_effect_element)
        else:
            logger.warning(f"{media_ref.generator_kind} generator missing fcpx_ref parameter.")

        common_attrs = {
            "name": item.name or "Generator",
            "lane": str(lane),
            "offset": _fcpx_time_str(item_start_time_in_timeline),
            "duration": _fcpx_time_str(item_duration),
            "start": "0s"
        }
        if effect_res_id:
            common_attrs["ref"] = effect_res_id

        # Handle enabled attribute - only add if explicitly disabled
        if hasattr(item, 'enabled') and item.enabled is False:
            common_attrs["enabled"] = "0"

        if media_ref.generator_kind == "fcpx_title":
            logger.debug(f"Title Attrs: {common_attrs}")
            item_elem = ET.Element("title", **common_attrs)
            text_style_ref_id = "ts_basic"
            text_style = ET.SubElement(ET.SubElement(item_elem, "text"), "text-style", ref=text_style_ref_id)
            text_style.text = media_ref.parameters.get('text', item.name or "Title Text")

        elif media_ref.generator_kind == "fcpx_video_placeholder":
            logger.debug(f"Video Attrs: {common_attrs}")
            item_elem = ET.Element("video", **common_attrs)

        else:
            # Fallback for unknown generators (won't have element created, handled in main loop)
            logger.warning(f"Unhandled GeneratorReference kind '{media_ref.generator_kind}'. Treating as implicit gap.")
            return None # Don't create an element

        if item_elem is not None:
             self._add_markers_to_element(item_elem, item)

        return item_elem

    # --- Main Population Logic ---

    def _populate_container_gap(self):
        """Iterates tracks and populates the main container gap."""
        logger.info("Populating main container gap.")
        for track in self.timeline.tracks:
            if track not in self.track_lane_map:
                logger.warning(f"Skipping track '{track.name}' with unhandled kind '{track.kind}'.")
                continue

            lane = self.track_lane_map[track]
            is_primary_track = (track.kind == otio.schema.TrackKind.Video and lane == self.primary_track_lane)
            logger.info(f"Processing track '{track.name}' (Kind: {track.kind}) -> Lane {lane} {'(Primary)' if is_primary_track else ''}")

            for item in track:
                item_elem = None
                # Simplified logic - call helper methods based on type
                if isinstance(item, otio.schema.Clip):
                    media_ref = item.media_reference
                    if isinstance(media_ref, otio.schema.ExternalReference):
                         item_elem = self._create_asset_clip_element(item, track, lane, is_primary_track)
                    elif isinstance(media_ref, otio.schema.GeneratorReference):
                         item_elem = self._create_generator_element(item, track, lane, is_primary_track, media_ref)
                    elif isinstance(media_ref, otio.schema.MissingReference):
                         logger.warning(f"Cannot write MissingReference '{item.name}'. Skipping.")
                         continue
                    else:
                         logger.warning(f"Unhandled media ref type {type(media_ref)} for clip '{item.name}'. Skipping.")
                         continue

                elif isinstance(item, otio.schema.Gap):
                    # Inner gaps are not added to the container gap structure
                    if is_primary_track:
                        logger.debug(f"Skipping creation of inner gap element on primary track: {item.name}")
                    continue # Always skip adding Gap elements inside the container

                else:
                     logger.warning(f"Skipping unhandled item type {type(item)} in track '{track.name}'")
                     continue

                if item_elem is not None:
                    self.main_container_gap.append(item_elem)


    def _finalize_resources(self):
        """Adds all collected resource elements to the <resources> section."""
        logger.info("Finalizing resources.")
        for fmt_id in sorted(self.format_elements.keys()):
            self.resources.append(self.format_elements[fmt_id])
        for asset_id in sorted(self.asset_elements.keys()):
            self.resources.append(self.asset_elements[asset_id])
        for effect_id in sorted(self.effect_elements.keys()):
            self.resources.append(self.effect_elements[effect_id])


    def _serialize_xml(self) -> str:
        """Serializes the final XML tree to a pretty-printed string."""
        logger.info("Serializing XML.")
        rough_string = ET.tostring(self.root, encoding='unicode')
        pretty_xml = "" # Initialize
        try:
            reparsed = xml.dom.minidom.parseString(rough_string)
            # minidom adds its own declaration, handle it below
            pretty_xml_bytes = reparsed.toprettyxml(indent="  ", encoding="utf-8")
            pretty_xml = pretty_xml_bytes.decode("utf-8")
            logger.info("Successfully indented XML using minidom.")
        except Exception as e:
            logger.error(f"Error during minidom indentation: {e}")
            logger.error("Falling back to unindented XML.")
            # Fallback uses the rough string which doesn't have the extra declaration
            pretty_xml = rough_string # Assign rough_string here

        # Remove minidom's XML declaration robustly
        # Find the end of the declaration '? >' and take the substring after it
        decl_end_index = pretty_xml.find('?>')
        if decl_end_index != -1:
            xml_content_only = pretty_xml[decl_end_index + 2:].strip()
        else:
            # If declaration wasn't found (e.g., in fallback rough_string), use the whole string
            xml_content_only = pretty_xml.strip()

        # Add our desired declaration and DOCTYPE
        final_decl = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'

        # Clean up extra newlines potentially added by toprettyxml
        # xml_cleaned = os.linesep.join([s for s in xml_content_only.splitlines() if s.strip()])
        # Let's just return the stripped content after our declaration for now
        # Revisit cleaning if needed

        return final_decl + xml_content_only.strip() # Use stripped content


    def build_xml_string(self) -> str:
        """Builds and returns the complete FCPXML string."""
        logger.info("Starting XML build process...")
        # Population happens via helper methods called during __init__ and here
        self._populate_container_gap()
        self._finalize_resources()
        return self._serialize_xml() 