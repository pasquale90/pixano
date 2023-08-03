# @Copyright: CEA-LIST/DIASI/SIALV/LVA (2023)
# @Author: CEA-LIST/DIASI/SIALV/LVA <pixano@cea.fr>
# @License: CECILL-C
#
# This software is a collaborative computer program whose purpose is to
# generate and explore labeled data for computer vision applications.
# This software is governed by the CeCILL-C license under French law and
# abiding by the rules of distribution of free software. You can use,
# modify and/ or redistribute the software under the terms of the CeCILL-C
# license as circulated by CEA, CNRS and INRIA at the following URL
#
# http://www.cecill.info

import datetime
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pyarrow as pa
import pyarrow.parquet as pq
from tqdm.auto import tqdm

from pixano.core import ImageType, ObjectAnnotation
from pixano.data import DatasetInfo
from pixano.data.exporters.exporter import Exporter
from pixano.utils import is_image_type, natural_key


class COCOExporter(Exporter):
    """Exporter class for COCO instances dataset

    Attributes:
        name (str): Dataset name
        description (str): Dataset description
        splits (list[str]): Dataset splits
        schema (pa.schema): Dataset schema
        partitioning (ds.partitioning): Dataset partitioning
    """

    def __init__(
        self,
        name: str,
        description: str,
        splits: list[str],
    ):
        """Initialize COCO Importer

        Args:
            name (str): Dataset name
            description (str): Dataset description
            splits (list[str]): Dataset splits
        """

        # Dataset views
        views = [pa.field("image", ImageType)]

        # Initialize Data Importer
        super().__init__(name, description, splits, views)

    def export_dataset(
        self,
        input_dir: Path,
        export_dir: Path,
        input_dbs: list = [],
        portable: bool = False,
    ):
        """Export dataset back to original format

        Args:
            input_dir (Path): Input directory
            export_dir (Path): Export directory
            input_dbs (list[str]): Input databases to export, all if []. Defaults to [].
            portable (bool, optional): True to export dataset portable media files. Defaults to False.
        """

        # Load spec.json
        input_info = DatasetInfo.parse_file(input_dir / "spec.json")

        # Create URI prefix
        media_dir = input_dir / "media"
        uri_prefix = media_dir.absolute().as_uri()
        export_uri_prefix = (export_dir / "media").absolute().as_uri()

        # If no splits provided, select all splits
        if not self.splits:
            splits = [s.name for s in os.scandir(input_dir / "db") if s.is_dir()]
        # Else, format provided splits
        else:
            splits = [
                f"split={s}" if not s.startswith("split=") else s for s in self.splits
            ]
        # Check if the splits exist
        for split in splits:
            split_dir = input_dir / "db" / split
            if not split_dir.exists():
                raise Exception(f"{split_dir} does not exist.")
            if not any(split_dir.iterdir()):
                raise Exception(f"{split_dir} is empty.")

        # If no input databases provided, select all input databases
        if not input_dbs:
            input_dbs = ["db"]
            for inf_json in sorted(list(input_dir.glob("db_infer_*/infer.json"))):
                input_dbs.append(inf_json.parent.name)
        # Else, format provided inference datasets
        else:
            input_dbs = [
                f"db_infer_{i}" if not i.startswith("db") else i for i in input_dbs
            ]

        # Check if the datasets exist
        for ds in input_dbs:
            ds_dir = input_dir / ds
            if not ds_dir.exists():
                raise Exception(f"{ds_dir} does not exist.")
            if not any(ds_dir.iterdir()):
                raise Exception(f"{ds_dir} is empty.")

        # Create export directory
        ann_dir = export_dir / f"annotations_[{','.join(input_dbs)}]"
        ann_dir.mkdir(parents=True, exist_ok=True)

        # Iterate on splits
        for split in splits:
            # List split files
            files = (input_dir / "db" / split).glob("*.parquet")
            files = sorted(files, key=lambda x: natural_key(x.name))
            split_name = split.replace("split=", "")

            # Create COCO json
            coco_json = {
                "info": {
                    "description": input_info.name,
                    "url": "N/A",
                    "version": f"v{datetime.datetime.now().strftime('%y%m%d.%H%M%S')}",
                    "year": datetime.date.today().year,
                    "contributor": "Exported from Pixano",
                    "date_created": datetime.date.today().isoformat(),
                },
                "licences": [
                    {
                        "url": "N/A",
                        "id": 1,
                        "name": "Unknown",
                    },
                ],
                "images": [],
                "annotations": [],
                "categories": [],
            }

            # Iterate on files
            for file in tqdm(files, desc=f"Processing {split_name} split", position=0):
                seen_category_ids = [None]

                # Load media table
                media_fields = [
                    field.name for field in self.schema if is_image_type(field.type)
                ]
                media_table = pq.read_table(file).select(["id"] + media_fields)

                # Load annotation tables
                ann_files = [input_dir / ds / split / file.name for ds in input_dbs]
                ann_tables = [pq.read_table(f).select(["objects"]) for f in ann_files]

                # Iterate on rows
                for row in tqdm(
                    range(media_table.num_rows),
                    desc=f"Processing {file.name}",
                    position=1,
                ):
                    media_row = media_table.take([row])
                    ann_rows = [ann_table.take([row]) for ann_table in ann_tables]
                    images = {}

                    for field in media_fields:
                        # Open image
                        images[field] = media_row[field][0]
                        if portable:
                            images[field].uri_prefix = export_uri_prefix
                        else:
                            images[field].uri_prefix = uri_prefix
                        im_filename = Path(urlparse(images[field].get_uri()).path).name
                        im_w, im_h = images[field].size
                        # Append image info
                        coco_json["images"].append(
                            {
                                "license": 1,
                                "coco_url": images[field].get_uri(),
                                "file_name": im_filename,
                                "height": im_h,
                                "width": im_w,
                                "id": media_row["id"][0].as_py(),
                            }
                        )

                    for ann_row in ann_rows:
                        anns = ann_row["objects"][0].as_py()

                        for ann in anns:
                            # Support for previous ObjectAnnotation type
                            if isinstance(ann, dict):
                                # Support for previous BBox type
                                if isinstance(ann["bbox"], list):
                                    ann["bbox"] = {
                                        "coords": ann["bbox"],
                                        "format": "xywh",
                                    }
                                ann = ObjectAnnotation.from_dict(ann)

                            # Append annotation
                            im_w, im_h = images[ann.view_id].size
                            coco_json["annotations"].append(
                                {
                                    "segmentation": ann.mask.to_urle(),
                                    "area": ann.area,
                                    "iscrowd": 0,
                                    "image_id": media_row["id"][0].as_py(),
                                    "bbox": ann.bbox.denormalize(im_h, im_w).coords,
                                    "category_id": ann.category_id,
                                    "category_name": ann.category_name,
                                    "id": ann.id,
                                }
                            )
                            # Append category if not seen yet
                            if (
                                ann.category_id not in seen_category_ids
                                and ann.category_name is not None
                            ):
                                coco_json["categories"].append(
                                    {
                                        "supercategory": "N/A",
                                        "id": ann.category_id,
                                        "name": ann.category_name,
                                    },
                                )
                                seen_category_ids.append(ann.category_id)

            # Sort categories
            coco_json["categories"] = sorted(
                coco_json["categories"], key=lambda c: c["id"]
            )

            # Save COCO json
            with open(ann_dir / f"instances_{split_name}.json", "w") as f:
                json.dump(coco_json, f)

            # Move media directory if portable and directory exists
            if portable:
                if media_dir.exists():
                    media_dir.rename(export_dir / "media")
                else:
                    raise Exception(
                        f"Activated portable option for export but {media_dir} does not exist."
                    )
