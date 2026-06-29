import { useEffect, useState, useMemo, useCallback } from "react";
import {
  MapContainer,
  TileLayer,
  Polygon,
  CircleMarker,
  Popup,
  LayersControl,
  LayerGroup,
  useMap,
} from "react-leaflet";
import { getTerritories } from "../services/api";
import type { GeoJSONCollection } from "../types";

interface Props {
  jobId: string;
  selectedSmId: string | null;
  onSmClick: (smId: string) => void;
  onFtcClick: (ftcId: string) => void;
}

const { Overlay } = LayersControl;

function FitBounds({ features }: { features: GeoJSONCollection["features"] }) {
  const map = useMap();
  useEffect(() => {
    const bounds: [number, number][] = [];
    features.forEach((f) => {
      const g = f.geometry;
      if (g.type === "Point") {
        bounds.push([g.coordinates[1], g.coordinates[0]]);
      } else if (g.type === "Polygon") {
        g.coordinates[0].forEach((c) => bounds.push([c[1], c[0]]));
      } else if (g.type === "MultiPolygon") {
        g.coordinates.forEach((poly) => {
          poly[0].forEach((c) => bounds.push([c[1], c[0]]));
        });
      }
    });
    if (bounds.length > 0) {
      map.fitBounds(bounds, { padding: [40, 40] });
    }
  }, [map, features]);
  return null;
}

export function MapView({
  jobId,
  selectedSmId,
  onSmClick,
  onFtcClick,
}: Props) {
  const [data, setData] = useState<GeoJSONCollection | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!jobId) return;
    setLoading(true);
    getTerritories(jobId)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [jobId]);

  const territoryFeatures = useMemo(
    () =>
      data?.features.filter((f) => f.properties.feature_type === "territory") ||
      [],
    [data],
  );

  const dealerFeatures = useMemo(
    () =>
      data?.features.filter((f) => f.properties.feature_type === "dealer") ||
      [],
    [data],
  );

  const getDealerStyle = useCallback(
    (feature: (typeof dealerFeatures)[0]) => {
      const isAnchor = feature.properties.is_anchor;
      const isStatic =
        feature.properties.dealer_type === "static";
      const isSelected =
        selectedSmId && feature.properties.sm_id === selectedSmId;
      return {
        radius: isAnchor ? 7 : isStatic ? 4 : 5,
        color: "#fff",
        fillColor: isSelected
          ? "#fbbf24"
          : (feature.properties.color as string) || "#4a90d9",
        weight: isAnchor ? 2 : 1,
        opacity: 1,
        fillOpacity: isSelected ? 1 : 0.7,
      };
    },
    [selectedSmId],
  );

  const getTerritoryStyle = useCallback(
    (feature: (typeof territoryFeatures)[0]) => {
      const isSelected =
        selectedSmId && feature.properties.sm_id === selectedSmId;
      return {
        color: isSelected ? "#fbbf24" : (feature.properties.color as string) || "#4a90d9",
        weight: isSelected ? 3 : 1.5,
        fillColor: (feature.properties.color as string) || "#4a90d9",
        fillOpacity: isSelected ? 0.35 : 0.15,
      };
    },
    [selectedSmId],
  );

  if (loading) {
    return (
      <div
        style={{
          background: "white",
          borderRadius: "12px",
          height: "500px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#999",
          fontSize: "14px",
          boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
        }}
      >
        Loading map data...
      </div>
    );
  }

  if (!data || territoryFeatures.length === 0) {
    return (
      <div
        style={{
          background: "white",
          borderRadius: "12px",
          height: "500px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#999",
          fontSize: "14px",
          boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
        }}
      >
        No territory data available for map visualization
      </div>
    );
  }

  return (
    <div
      style={{
        background: "white",
        borderRadius: "12px",
        overflow: "hidden",
        boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
        height: "500px",
      }}
    >
      <MapContainer
        center={[20.5937, 78.9629]}
        zoom={5}
        style={{ width: "100%", height: "100%" }}
        scrollWheelZoom={true}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds features={data.features} />

        <LayersControl position="topright">
          <Overlay checked name="Territories">
            <LayerGroup>
              {territoryFeatures.map((f, i) => {
                const g = f.geometry;
                if (g.type !== "Polygon") return null;
                const latLngs = g.coordinates[0].map(
                  (c) => [c[1], c[0]] as [number, number],
                );
                const props = f.properties;
                return (
                  <Polygon
                    key={`terr-${i}`}
                    positions={latLngs}
                    pathOptions={getTerritoryStyle(f)}
                    eventHandlers={{
                      click: () => onSmClick(props.sm_id),
                    }}
                  >
                    <Popup>
                      <div style={{ fontSize: "13px", minWidth: "160px" }}>
                        <strong>SM:</strong> {props.sm_id}
                        <br />
                        <strong>FTC:</strong> {props.ftc_id}
                        <br />
                        <strong>Dealers:</strong>{" "}
                        {props.dealer_count ?? "N/A"}
                        <br />
                        {props.anchor_dealer && (
                          <>
                            <strong>Anchor:</strong>{" "}
                            {props.anchor_dealer}
                          </>
                        )}
                      </div>
                    </Popup>
                  </Polygon>
                );
              })}
            </LayerGroup>
          </Overlay>

          <Overlay checked name="Dealers">
            <LayerGroup>
              {dealerFeatures.map((f, i) => {
                const g = f.geometry;
                if (g.type !== "Point") return null;
                const props = f.properties;
                const style = getDealerStyle(f);
                return (
                  <CircleMarker
                    key={`dlr-${i}`}
                    center={[g.coordinates[1], g.coordinates[0]]}
                    radius={style.radius}
                    pathOptions={{
                      color: style.color,
                      fillColor: style.fillColor,
                      weight: style.weight,
                      opacity: style.opacity,
                      fillOpacity: style.fillOpacity,
                    }}
                    eventHandlers={{
                      click: () => onFtcClick(props.ftc_id),
                    }}
                  >
                    <Popup>
                      <div style={{ fontSize: "13px", minWidth: "160px" }}>
                        <strong>Dealer:</strong> {props.dealer_id}
                        <br />
                        <strong>Type:</strong>{" "}
                        {props.dealer_type?.toUpperCase()}
                        <br />
                        <strong>SM:</strong> {props.sm_id}
                        <br />
                        <strong>FTC:</strong> {props.ftc_id}
                        <br />
                        <strong>Cases/day:</strong>{" "}
                        {props.cases_per_day?.toFixed(1) ?? "0.0"}
                        <br />
                        {props.is_anchor && (
                          <span
                            style={{
                              color: "#166534",
                              fontWeight: 600,
                              fontSize: "11px",
                            }}
                          >
                            ANCHOR DEALER
                          </span>
                        )}
                      </div>
                    </Popup>
                  </CircleMarker>
                );
              })}
            </LayerGroup>
          </Overlay>
        </LayersControl>
      </MapContainer>
    </div>
  );
}
