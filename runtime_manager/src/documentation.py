# Copyright (c) 2025 Robert Bosch GmbH
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Handles parsing of system documentation.
"""

import os
import pathlib
import base64
import re


class MarkdownImageEmbedder:
    """Embeds images as base64-encoded string into a markdown file."""

    # regular expression to match markdown images
    _markdown_image_regex = r"!\[(.*?)\]\(\s*(?!https?://)(.*?)\s*\)"

    def __init__(self, input_markdown: str, markdown_dir: os.PathLike) -> None:
        self.input_markdown = input_markdown
        self.markdown_dir = markdown_dir

    def extract_images_paths_from_markdown(self) -> list[os.PathLike]:
        """Extract all images paths from a markdown and return them as a list."""
        matches = re.findall(MarkdownImageEmbedder._markdown_image_regex, self.input_markdown)
        images_paths = []
        for match in matches:
            images_paths.append(match[1])
        return images_paths

    def _encode_image(self, image_path: os.PathLike):
        """Opens the image and returns the image content as base64-encoded string."""
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Referenced image path '{image_path}' in markdown file cannot be found!")
        with open(image_path, "rb") as image_file:
            # encode image to base64 string
            image_b64_bytes = base64.b64encode(image_file.read())
            image_b64_string = image_b64_bytes.decode('utf-8')
        # remove '.' from file ending and make file ending lower case to get pure image format identifier
        image_format = str.replace(str.lower(pathlib.Path(image_path).suffix), '.', '')
        if image_format == 'jpeg':
            image_format = 'jpg'
        if image_format in ('png', 'jpg'):
            string = f"![](data:image/{image_format};base64,{image_b64_string})"
        else:
            raise ValueError(f"Unexpected image file format '{image_format}' for markdown content!")
        return string

    def embed_images_in_markdown(self, base_dir: str) -> str:
        """Embeds for each image link in the markdown file the base64-encoded string for the image content.

        The base_dir is added in front of the image paths inside the input markdown to extract the image
        content at a valid path in the file system.
        """
        output_markdown = ''
        current_position = 0
        # iterate over all images in input markdown and replace by base64-encoded image content
        for match in re.finditer(MarkdownImageEmbedder._markdown_image_regex, self.input_markdown):
            end, newstart = match.span()
            output_markdown += self.input_markdown[current_position:end]
            image_filename = os.path.join(base_dir, self.markdown_dir, match.group(2))
            replacement_string = self._encode_image(image_filename)
            output_markdown += replacement_string
            current_position = newstart
        output_markdown += self.input_markdown[current_position:]
        return output_markdown
