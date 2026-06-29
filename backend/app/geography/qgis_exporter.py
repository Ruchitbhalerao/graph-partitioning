from typing import List, Dict, Optional, Any
import json
import os
import zipfile
import csv
from datetime import datetime
from shapely.geometry import mapping, Polygon, Point, LineString

def _get_fiona():
    """Lazy import fiona to avoid startup crash when GDAL is not installed."""
    import fiona
    return fiona

def _from_epsg(epsg):
    return _get_fiona().crs.from_epsg(epsg)

from ..models.schemas import DealerRecord, FTCRecord
from ..models.enums import DealerType
from .polygon_generator import TerritoryPolygonGenerator
from .routing import RouteOptimizer


TERRITORY_STYLE_QML = """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis>
  <classificationattribute>ftc_id</classificationattribute>
  <renderer-v2 type="categorizedSymbol" enableorderby="1" attr="ftc_id">
    <categories>
      <category symbol="0" value="" label="Territory"/>
    </categories>
    <symbols>
      <symbol name="0" type="fill" clip_to_extent="1" alpha="1">
        <layer class="SimpleFill" pass="0" enabled="1" locked="0">
          <prop k="border_width_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="color" v="190,207,255,76"/>
          <prop k="joinstyle" v="bevel"/>
          <prop k="offset" v="0,0"/>
          <prop k="offset_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="outline_color" v="79,106,184,255"/>
          <prop k="outline_style" v="solid"/>
          <prop k="outline_width" v="0.46"/>
          <prop k="style" v="solid"/>
        </layer>
        <layer class="SimpleLine" pass="0" enabled="1" locked="0">
          <prop k="color" v="79,106,184,255"/>
          <prop k="width" v="0.46"/>
          <prop k="penstyle" v="solid"/>
        </layer>
      </symbol>
    </symbols>
    <labeling type="simple">
      <settings>
        <labelStyle>labelStyle>
      </settings>
    </labeling>
  </renderer-v2>
</qgis>"""

DEALER_STYLE_QML = """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis>
  <classificationattribute>dealer_type</classificationattribute>
  <renderer-v2 type="categorizedSymbol" attr="dealer_type">
    <categories>
      <category symbol="0" value="static" label="Static"/>
      <category symbol="1" value="mobile" label="Mobile"/>
    </categories>
    <symbols>
      <symbol name="0" type="marker" alpha="1">
        <layer class="SimpleMarker" pass="0" enabled="1" locked="0">
          <prop k="color" v="232,113,141,255"/>
          <prop k="size" v="3.0"/>
          <prop k="outline_color" v="0,0,0,128"/>
          <prop k="outline_width" v="0.4"/>
        </layer>
      </symbol>
      <symbol name="1" type="marker" alpha="1">
        <layer class="SimpleMarker" pass="0" enabled="1" locked="0">
          <prop k="color" v="87,178,255,255"/>
          <prop k="size" v="4.0"/>
          <prop k="outline_color" v="0,0,0,128"/>
          <prop k="outline_width" v="0.4"/>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
</qgis>"""

PRJ_TEMPLATE = 'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["Degree",0.017453292519943295]]'


class QGISExporter:
    def __init__(
        self,
        output_dir: str = "/tmp/outputs",
        crs: str = "EPSG:4326",
    ):
        self.output_dir = output_dir
        self.crs = crs
        self.polygon_generator = TerritoryPolygonGenerator()
        self.route_optimizer = RouteOptimizer()

    def export_all(
        self,
        job_id: str,
        results: Dict[str, Dict],
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
        include_routes: bool = False,
        style_info: Optional[Dict] = None,
    ) -> Dict[str, str]:
        job_dir = os.path.join(self.output_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)

        output_files = {}

        # GeoJSON layers
        output_files["territories_geojson"] = self._export_territory_polygons(
            job_dir, job_id, results, dealers, ftcs
        )
        output_files["dealers_geojson"] = self._export_dealer_points(
            job_dir, job_id, results, dealers
        )
        output_files["assignments_csv"] = self._export_assignments(
            job_dir, job_id, results
        )
        output_files["dealers_csv"] = self._export_dealers_csv(
            job_dir, job_id, results, dealers
        )
        output_files["sm_summary_csv"] = self._export_sm_summary_csv(
            job_dir, job_id, results
        )

        if include_routes:
            routes_file = self._export_routes(
                job_dir, job_id, results, dealers
            )
            if routes_file:
                output_files["routes_geojson"] = routes_file

        output_files["sm_boundaries_geojson"] = self._export_sm_boundaries(
            job_dir, job_id, results, dealers
        )

        # Shapefile package
        shapefile_zip = self._export_shapefile_package(
            job_dir, job_id, results, dealers, ftcs
        )
        if shapefile_zip:
            output_files["shapefile_zip"] = shapefile_zip

        # QGIS style files
        style_dir = os.path.join(job_dir, "styles")
        os.makedirs(style_dir, exist_ok=True)
        self._write_qml(style_dir, f"{job_id}_territories.qml", TERRITORY_STYLE_QML)
        self._write_qml(style_dir, f"{job_id}_dealers.qml", DEALER_STYLE_QML)
        output_files["styles_dir"] = style_dir

        # Metadata
        config = (style_info or {}).get("config", {})
        output_files["metadata_json"] = self._export_metadata(
            job_dir, job_id, results, dealers, ftcs, config
        )

        # Export manifest
        manifest = self._build_manifest(output_files, job_dir, job_id)
        manifest_path = os.path.join(job_dir, f"{job_id}_manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        output_files["manifest_json"] = manifest_path

        # QGIS project file
        self._export_qgis_project(job_dir, job_id)
        output_files["qgis_project"] = os.path.join(job_dir, f"{job_id}.qgs")

        return output_files

    def _write_qml(self, style_dir: str, filename: str, content: str):
        path = os.path.join(style_dir, filename)
        with open(path, "w") as f:
            f.write(content)

    def _build_manifest(
        self, output_files: Dict[str, str], job_dir: str, job_id: str
    ) -> Dict:
        entries = []
        for key, path in output_files.items():
            if os.path.exists(path):
                size_bytes = os.path.getsize(path)
                entries.append({
                    "key": key,
                    "filename": os.path.basename(path),
                    "size_bytes": size_bytes,
                    "size_label": self._format_size(size_bytes),
                })
        return {
            "job_id": job_id,
            "generated_at": datetime.now().isoformat(),
            "files": entries,
            "total_files": len(entries),
        }

    @staticmethod
    def _format_size(bytes_: int) -> str:
        if bytes_ < 1024:
            return f"{bytes_} B"
        elif bytes_ < 1024 * 1024:
            return f"{bytes_ / 1024:.1f} KB"
        else:
            return f"{bytes_ / (1024 * 1024):.1f} MB"

    def _export_territory_polygons(
        self, job_dir: str, job_id: str,
        results: Dict[str, Dict], dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
    ) -> str:
        features = []
        for sm_id, sm_result in results.items():
            assignments = sm_result.get("assignments", {})
            territories = self.polygon_generator.generate_all_territories(
                assignments, dealers
            )
            for ftc_id, polygon in territories.items():
                if polygon and not polygon.is_empty:
                    ftc = next((f for f in ftcs if f.FTC_id == ftc_id), None)
                    dealer_ids = assignments.get(ftc_id, [])
                    dealer_count = len(dealer_ids)
                    total_cases = sum(
                        d.Average_cases_per_day
                        for d in dealers if d.Dealer_id in dealer_ids
                    )
                    static_count = sum(
                        1 for d in dealers
                        if d.Dealer_id in dealer_ids
                        and d.Dealer_type == DealerType.STATIC
                    )
                    mobile_count = dealer_count - static_count
                    feature = {
                        "type": "Feature",
                        "properties": {
                            "sm_id": sm_id,
                            "ftc_id": ftc_id,
                            "dealer_count": dealer_count,
                            "static_count": static_count,
                            "mobile_count": mobile_count,
                            "total_cases": round(total_cases, 2),
                            "area_sqkm": round(polygon.area * 111.32 ** 2, 2),
                            "product_group": ftc.Product_Group.value if ftc else "",
                            "vintage_years": ftc.FTC_VIntage if ftc else 0,
                            "anchor_dealer": sm_result.get("anchors", {}).get(ftc_id, ""),
                        },
                        "geometry": mapping(polygon),
                    }
                    features.append(feature)

        geojson = {
            "type": "FeatureCollection",
            "features": features,
            "crs": {"type": "name", "properties": {"name": self.crs}},
        }
        filepath = os.path.join(job_dir, f"{job_id}_territories.geojson")
        with open(filepath, "w") as f:
            json.dump(geojson, f, indent=2)
        return filepath

    def _export_dealer_points(
        self, job_dir: str, job_id: str,
        results: Dict[str, Dict], dealers: List[DealerRecord],
    ) -> str:
        ftc_dealer_map = {}
        for sm_result in results.values():
            for ftc_id, dealer_ids in sm_result.get("assignments", {}).items():
                for d_id in dealer_ids:
                    ftc_dealer_map[d_id] = ftc_id

        features = []
        for d in dealers:
            ftc_id = ftc_dealer_map.get(d.Dealer_id, "")
            feature = {
                "type": "Feature",
                "properties": {
                    "dealer_id": d.Dealer_id,
                    "sm_id": d.SM_id,
                    "dealer_type": d.Dealer_type.value,
                    "product_group": d.Product_group.value,
                    "avg_cases": d.Average_cases_per_day,
                    "disbursements": d.Count_BFL_disbursement,
                    "assigned_ftc": ftc_id,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [d.Dealer_longitude, d.Dealer_latitude],
                },
            }
            features.append(feature)

        geojson = {
            "type": "FeatureCollection",
            "features": features,
            "crs": {"type": "name", "properties": {"name": self.crs}},
        }
        filepath = os.path.join(job_dir, f"{job_id}_dealers.geojson")
        with open(filepath, "w") as f:
            json.dump(geojson, f, indent=2)
        return filepath

    def _export_assignments(
        self, job_dir: str, job_id: str, results: Dict[str, Dict],
    ) -> str:
        filepath = os.path.join(job_dir, f"{job_id}_assignments.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "SM_ID", "FTC_ID", "Dealer_ID", "Is_Anchor"
            ])
            for sm_id, sm_result in results.items():
                anchors = sm_result.get("anchors", {})
                for ftc_id, dealer_ids in sm_result.get("assignments", {}).items():
                    for dealer_id in dealer_ids:
                        writer.writerow([
                            sm_id, ftc_id, dealer_id,
                            "Yes" if anchors.get(ftc_id) == dealer_id else "No",
                        ])
        return filepath

    def _export_dealers_csv(
        self, job_dir: str, job_id: str,
        results: Dict[str, Dict], dealers: List[DealerRecord],
    ) -> str:
        ftc_dealer_map = {}
        for sm_result in results.values():
            for ftc_id, dealer_ids in sm_result.get("assignments", {}).items():
                for d_id in dealer_ids:
                    ftc_dealer_map[d_id] = ftc_id

        filepath = os.path.join(job_dir, f"{job_id}_dealers.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Dealer_ID", "SM_ID", "Dealer_Type", "Product_Group",
                "Latitude", "Longitude", "Avg_Cases_Per_Day",
                "BFL_Disbursements", "Assigned_FTC",
            ])
            for d in dealers:
                writer.writerow([
                    d.Dealer_id, d.SM_id, d.Dealer_type.value,
                    d.Product_group.value, d.Dealer_latitude,
                    d.Dealer_longitude, d.Average_cases_per_day,
                    d.Count_BFL_disbursement,
                    ftc_dealer_map.get(d.Dealer_id, ""),
                ])
        return filepath

    def _export_sm_summary_csv(
        self, job_dir: str, job_id: str, results: Dict[str, Dict],
    ) -> str:
        filepath = os.path.join(job_dir, f"{job_id}_sm_summary.csv")
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "SM_ID", "FTC_Count", "Static_Dealers", "Mobile_Dealers",
                "Total_Dealers", "Is_Valid",
            ])
            for sm_id, sm_result in results.items():
                writer.writerow([
                    sm_id,
                    sm_result.get("ftc_count", 0),
                    sm_result.get("static_dealers", 0),
                    sm_result.get("mobile_dealers", 0),
                    sm_result.get("static_dealers", 0) + sm_result.get("mobile_dealers", 0),
                    "Yes" if sm_result.get("is_valid", False) else "No",
                ])
        return filepath

    def _export_routes(
        self, job_dir: str, job_id: str,
        results: Dict[str, Dict], dealers: List[DealerRecord],
    ) -> Optional[str]:
        dealer_map = {d.Dealer_id: d for d in dealers}
        features = []
        for sm_result in results.values():
            assignments = sm_result.get("assignments", {})
            anchors = sm_result.get("anchors", {})
            routes = self.route_optimizer.optimize_all_routes(
                assignments, dealers, anchors
            )
            for ftc_id, route in routes.items():
                gj = self.route_optimizer.generate_route_geojson(route, dealer_map)
                features.append(gj)

        if not features:
            return None

        geojson = {
            "type": "FeatureCollection",
            "features": features,
        }
        filepath = os.path.join(job_dir, f"{job_id}_routes.geojson")
        with open(filepath, "w") as f:
            json.dump(geojson, f, indent=2)
        return filepath

    def _export_sm_boundaries(
        self, job_dir: str, job_id: str,
        results: Dict[str, Dict], dealers: List[DealerRecord],
    ) -> str:
        features = []
        for sm_id, sm_result in results.items():
            assignments = sm_result.get("assignments", {})
            ftc_polygons = []
            territories = self.polygon_generator.generate_all_territories(
                assignments, dealers
            )
            for poly in territories.values():
                if poly and not poly.is_empty:
                    ftc_polygons.append(poly)
            sm_polygon = self.polygon_generator.generate_sm_region_polygon(ftc_polygons)
            if sm_polygon and not sm_polygon.is_empty:
                feature = {
                    "type": "Feature",
                    "properties": {
                        "sm_id": sm_id,
                        "ftc_count": sm_result.get("ftc_count", 0),
                        "dealer_count": (
                            sm_result.get("static_dealers", 0)
                            + sm_result.get("mobile_dealers", 0)
                        ),
                        "area_sqkm": round(sm_polygon.area * 111.32 ** 2, 2),
                    },
                    "geometry": mapping(sm_polygon),
                }
                features.append(feature)
        geojson = {
            "type": "FeatureCollection",
            "features": features,
        }
        filepath = os.path.join(job_dir, f"{job_id}_sm_boundaries.geojson")
        with open(filepath, "w") as f:
            json.dump(geojson, f, indent=2)
        return filepath

    def _export_shapefile_package(
        self, job_dir: str, job_id: str,
        results: Dict[str, Dict], dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
    ) -> Optional[str]:
        try:
            shp_dir = os.path.join(job_dir, f"{job_id}_shapefile")
            os.makedirs(shp_dir, exist_ok=True)

            # Territories shapefile
            schema = {
                "geometry": "Polygon",
                "properties": {
                    "sm_id": "str",
                    "ftc_id": "str",
                    "dlr_cnt": "int",
                    "static": "int",
                    "mobile": "int",
                    "tot_cases": "float",
                    "area_sqkm": "float",
                },
            }
            shp_path = os.path.join(shp_dir, f"{job_id}_territories.shp")
            with _get_fiona().open(
                shp_path, "w", driver="ESRI Shapefile",
                schema=schema, crs=_from_epsg(4326),
            ) as shp:
                for sm_id, sm_result in results.items():
                    assignments = sm_result.get("assignments", {})
                    territories = self.polygon_generator.generate_all_territories(
                        assignments, dealers
                    )
                    for ftc_id, polygon in territories.items():
                        if polygon and not polygon.is_empty:
                            dealer_ids = assignments.get(ftc_id, [])
                            total_cases = sum(
                                d.Average_cases_per_day
                                for d in dealers if d.Dealer_id in dealer_ids
                            )
                            static_count = sum(
                                1 for d in dealers
                                if d.Dealer_id in dealer_ids
                                and d.Dealer_type == DealerType.STATIC
                            )
                            mobile_count = len(dealer_ids) - static_count
                            shp.write({
                                "geometry": mapping(polygon),
                                "properties": {
                                    "sm_id": sm_id,
                                    "ftc_id": ftc_id,
                                    "dlr_cnt": len(dealer_ids),
                                    "static": static_count,
                                    "mobile": mobile_count,
                                    "tot_cases": round(total_cases, 2),
                                    "area_sqkm": round(polygon.area * 111.32 ** 2, 2),
                                },
                            })

            # Dealers shapefile
            dealer_schema = {
                "geometry": "Point",
                "properties": {
                    "dlr_id": "str",
                    "sm_id": "str",
                    "type": "str",
                    "group": "str",
                    "cases": "float",
                    "asgn_ftc": "str",
                },
            }
            dlr_shp = os.path.join(shp_dir, f"{job_id}_dealers.shp")
            ftc_dealer_map = {}
            for sm_result in results.values():
                for ftc_id, dealer_ids in sm_result.get("assignments", {}).items():
                    for d_id in dealer_ids:
                        ftc_dealer_map[d_id] = ftc_id
            with _get_fiona().open(
                dlr_shp, "w", driver="ESRI Shapefile",
                schema=dealer_schema, crs=_from_epsg(4326),
            ) as shp:
                for d in dealers:
                    shp.write({
                        "geometry": {"type": "Point", "coordinates": [d.Dealer_longitude, d.Dealer_latitude]},
                        "properties": {
                            "dlr_id": d.Dealer_id,
                            "sm_id": d.SM_id,
                            "type": d.Dealer_type.value,
                            "group": d.Product_group.value,
                            "cases": d.Average_cases_per_day,
                            "asgn_ftc": ftc_dealer_map.get(d.Dealer_id, ""),
                        },
                    })

            # Write .prj file
            prj_path = os.path.join(shp_dir, f"{job_id}_territories.prj")
            with open(prj_path, "w") as f:
                f.write(PRJ_TEMPLATE)

            # Zip everything
            zip_path = os.path.join(job_dir, f"{job_id}_shapefile.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname in sorted(os.listdir(shp_dir)):
                    fpath = os.path.join(shp_dir, fname)
                    zf.write(fpath, arcname=fname)

            import shutil
            shutil.rmtree(shp_dir, ignore_errors=True)
            return zip_path
        except Exception:
            return None

    def _export_metadata(
        self, job_dir: str, job_id: str,
        results: Dict[str, Dict], dealers: List[DealerRecord],
        ftcs: List[FTCRecord], config: Optional[Dict] = None,
    ) -> str:
        total_static = sum(r.get("static_dealers", 0) for r in results.values())
        total_mobile = sum(r.get("mobile_dealers", 0) for r in results.values())
        total_ftcs_count = sum(r.get("ftc_count", 0) for r in results.values())
        valid_regions = sum(1 for r in results.values() if r.get("is_valid", False))
        total_cases = sum(d.Average_cases_per_day for d in dealers)
        product_groups = sorted(set(d.Product_group.value for d in dealers))

        metadata = {
            "job_id": job_id,
            "generated_at": datetime.now().isoformat(),
            "crs": self.crs,
            "coordinate_system": "WGS 84 (EPSG:4326)",
            "total_dealers": total_static + total_mobile,
            "static_dealers": total_static,
            "mobile_dealers": total_mobile,
            "total_ftcs": total_ftcs_count,
            "total_sm_regions": len(results),
            "valid_regions": valid_regions,
            "total_cases_per_day": round(total_cases, 2),
            "product_groups": product_groups,
            "source_data": {
                "dealers_file": "Dealers sheet",
                "ftcs_file": "FTC sheet",
                "relationships_file": "FTC-Dealer sheet",
                "total_records": {
                    "dealers": len(dealers),
                    "ftcs": len(ftcs),
                },
            },
            "optimization_parameters": {
                "optimization_type": "hybrid_graph_partitioning",
                "refinement_algorithm": "tabu_search",
                "territory_generation": "multilevel_graph_partitioning",
                **({"config": config} if config else {}),
            },
            "output_files": {
                "territories": f"{job_id}_territories.geojson",
                "dealers": f"{job_id}_dealers.geojson",
                "assignments": f"{job_id}_assignments.csv",
                "dealers_csv": f"{job_id}_dealers.csv",
                "sm_summary": f"{job_id}_sm_summary.csv",
                "sm_boundaries": f"{job_id}_sm_boundaries.geojson",
                "shapefile_package": f"{job_id}_shapefile.zip",
                "metadata": f"{job_id}_metadata.json",
                "manifest": f"{job_id}_manifest.json",
                "qgis_project": f"{job_id}.qgs",
            },
            "cartographic_notes": {
                "recommended_scale": "1:50,000 to 1:500,000",
                "base_map": "OpenStreetMap or satellite imagery",
                "label_field_territories": "ftc_id",
                "label_field_dealers": "dealer_id",
                "classification_field": "dealer_type (static/mobile)",
            },
            "data_dictionary": {
                "territories_geojson": {
                    "sm_id": "Sales Manager region identifier",
                    "ftc_id": "Field Territory Coordinator identifier",
                    "dealer_count": "Total dealers assigned to the territory",
                    "static_count": "Number of static dealers",
                    "mobile_count": "Number of mobile dealers",
                    "total_cases": "Sum of average daily cases",
                    "area_sqkm": "Territory area in square kilometers",
                    "product_group": "Product category",
                    "vintage_years": "FTC experience in years",
                    "anchor_dealer": "Primary anchor dealer for the territory",
                },
                "dealers_geojson": {
                    "dealer_id": "Unique dealer identifier",
                    "sm_id": "Sales Manager region",
                    "dealer_type": "static or mobile classification",
                    "product_group": "Product category handled",
                    "avg_cases": "Average cases per day",
                    "disbursements": "BFL disbursement count",
                    "assigned_ftc": "FTC assigned to this dealer",
                },
            },
        }
        filepath = os.path.join(job_dir, f"{job_id}_metadata.json")
        with open(filepath, "w") as f:
            json.dump(metadata, f, indent=2)
        return filepath

    def _export_qgis_project(self, job_dir: str, job_id: str):
        project_path = os.path.join(job_dir, f"{job_id}.qgs")
        with open(project_path, "w") as f:
            f.write(f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis projectname="Territory Optimization - {job_id}">
  <title>Territory Optimization Results</title>
  <layer-tree-group>
    <layer-tree-layer name="Territories" source="{job_id}_territories.geojson" providerKey="ogr"/>
    <layer-tree-layer name="Dealers" source="{job_id}_dealers.geojson" providerKey="ogr"/>
    <layer-tree-layer name="SM Boundaries" source="{job_id}_sm_boundaries.geojson" providerKey="ogr"/>
  </layer-tree-group>
  <mapcanvas>
    <units>degrees</units>
    <extent>
      <xmin>68.0</xmin>
      <ymin>6.0</ymin>
      <xmax>98.0</xmax>
      <ymax>38.0</ymax>
    </extent>
    <projections>
      <crs>
        <spatialrefsys>
          <wkt>GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]</wkt>
          <proj4>+proj=longlat +datum=WGS84 +no_defs</proj4>
        </spatialrefsys>
      </crs>
    </projections>
  </mapcanvas>
</qgis>""")
