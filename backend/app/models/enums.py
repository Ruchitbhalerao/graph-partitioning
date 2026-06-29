from enum import Enum


class DealerType(str, Enum):
    STATIC = "static"
    MOBILE = "mobile"


class ProductGroup(str, Enum):
    PRODUCT_A = "Product_A"
    PRODUCT_B = "Product_B"
    PRODUCT_C = "Product_C"


class OptimizationPhase(str, Enum):
    GRAPH_CONSTRUCTION = "graph_construction"
    INITIAL_TERRITORIES = "initial_territories"
    TERRITORY_REFINEMENT = "territory_refinement"
    VALIDATION = "validation"
    POLYGON_GENERATION = "polygon_generation"
    COMPLETE = "complete"
    FAILED = "failed"


class OutputFormat(str, Enum):
    GEOJSON = "geojson"
    SHAPEFILE = "shapefile"
    CSV = "csv"
    EXCEL = "excel"
