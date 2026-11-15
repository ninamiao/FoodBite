
"use client";

import { useEffect, useState } from "react";
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  useMap,
} from "react-leaflet";
import { divIcon, type LatLngExpression } from "leaflet";
import type { CuratedEvent } from "../lib/events";

type Props = {
  events: CuratedEvent[];
  plannedIds: string[];
  onTogglePlan: (id: string) => void;
};

const EVENT_COORDINATES: Record<string, [number, number]> = {
    // Geisel Library
    "event-e41bafbc36e3b6b9": [32.88116, -117.237651],

    // Sanford Consortium for Regenerative Medicine
    "event-d24f898cfbcfece7": [32.88943, -117.24386],

    // Triton Health and Wellness Building
    "event-4e7fc2b6ea7e36bc": [32.8779267, -117.2364606],

    // Triton Administrative Services Building
    "event-43c6054370d9f406": [32.8773698, -117.2360418],

    // Malk Hall
    "event-f308db6c5cb93df0": [32.8830355, -117.2403434],
    "event-d936407c50fe8612": [32.8830355, -117.2403434],

    // Student Center B
    "event-4336df7bdd1a6252": [32.8772926, -117.2387881],
};


function createMarkerIcon(
  number: number,
  selected: boolean,
  planned: boolean,
) {
  return divIcon({
    className: "freebite-map-marker",
    html: `<span class="${planned ? "planned" : ""} ${selected ? "selected" : ""}">
      <span class="marker-number">${number}</span>
    </span>`,
    iconSize: [36, 42],
    iconAnchor: [18, 42],
    popupAnchor: [0, -38],
  });
}
  

function MapController({
  selectedEvent,
}: {
  selectedEvent: CuratedEvent | null;
}) {
  const map = useMap();

  useEffect(() => {
    if (!selectedEvent) return;

    const coordinates = EVENT_COORDINATES[selectedEvent.id];

    if (coordinates) {
      map.flyTo(coordinates, 17, { duration: 0.7 });
    }
  }, [map, selectedEvent]);

  return null;
}

function eventDate(event: CuratedEvent) {
  if (!event.date) return "Date to be confirmed";

  return new Date(`${event.date}T12:00:00`).toLocaleDateString(
    "en-US",
    {
      month: "short",
      day: "numeric",
      year: "numeric",
    },
  );
}

export default function EventMap({
  events,
  plannedIds,
  onTogglePlan,
}: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Events with map coordinates always appear first.
  const sortedEvents = [...events].sort((a, b) => {
    const aHasLocation = Boolean(EVENT_COORDINATES[a.id]);
    const bHasLocation = Boolean(EVENT_COORDINATES[b.id]);

    return Number(bHasLocation) - Number(aHasLocation);
  });

  const mappedEvents = sortedEvents.filter(
    (event) => EVENT_COORDINATES[event.id],
  );

  const selectedEvent =
    events.find((event) => event.id === selectedId) ?? null;

  const center: LatLngExpression = [32.8795, -117.237];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">Explore the map</h2>
        <p className="mt-1 text-sm text-[#89938A]">
          {mappedEvents.length} of {events.length} events have map locations.
        </p>
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">

        {/* Sticky map */}
        <div className="sticky top-4 z-10 overflow-hidden rounded-2xl border border-[#E5E9E2] bg-white shadow-sm">
          <MapContainer
            center={center}
            zoom={15}
            scrollWheelZoom={true}
            className="h-[360px] w-full lg:h-[calc(100vh-10rem)] lg:max-h-[760px]"
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            <MapController selectedEvent={selectedEvent} />

            {mappedEvents.map((event, index) => {
              const position = EVENT_COORDINATES[event.id];
              const selected = selectedId === event.id;
              const planned = plannedIds.includes(event.id);

              return (
                <Marker
                  key={event.id}
                  position={position}
                  icon={createMarkerIcon(index + 1, selected, planned)}
                  eventHandlers={{
                    click: () => setSelectedId(event.id),
                  }}
                >
                  <Popup>
                    <div className="min-w-40">
                      <strong>{event.title}</strong>
                      <p className="mt-1 text-sm">{eventDate(event)}</p>
                      <p className="mt-1 text-sm">
                        {event.location ?? event.address}
                      </p>
                      {event.food_description && (
                        <p className="mt-2 text-sm">
                          {event.food_description}
                        </p>
                      )}
                    </div>
                  </Popup>
                </Marker>
              );
            })}
          </MapContainer>
        </div>

        {/* Independently scrollable event list */}
        <div className="max-h-[55vh] space-y-3 overflow-y-auto pr-1 lg:max-h-[calc(100vh-10rem)]">
          <div className="sticky top-0 z-[5] bg-[#F8FAF6] py-2">
            <h3 className="text-sm font-semibold">
              Events ({sortedEvents.length})
            </h3>
          </div>

          {sortedEvents.map((event) => {
            const hasCoordinates = Boolean(
              EVENT_COORDINATES[event.id],
            );
            const planned = plannedIds.includes(event.id);
            const selected = selectedId === event.id;

            return (
              <div
                key={event.id}
                className={`rounded-xl border bg-white p-4 transition ${
                  selected
                    ? "border-[#567B60] ring-2 ring-[#567B60]"
                    : "border-[#E5E9E2]"
                }`}
              >
                <button
                  type="button"
                  onClick={() => setSelectedId(event.id)}
                  className="w-full text-left"
                >
                  <div className="flex items-start justify-between gap-3">
                    <h4 className="text-sm font-semibold">
                      {event.title}
                    </h4>

                    <span
                      className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold ${
                        hasCoordinates
                          ? "bg-[#EAF1E8] text-[#42674A]"
                          : "bg-[#F3F1EC] text-[#82796D]"
                      }`}
                    >
                      {hasCoordinates ? "On map" : "Not pinned"}
                    </span>
                    {planned && (
                      <span className="shrink-0 rounded-full bg-[#FCE9DA] px-2 py-1 text-[10px] font-semibold text-[#A65D32]">
                        ✓ Planned
                      </span>
                    )}
                  </div>

                  <p className="mt-2 text-xs text-[#89938A]">
                    {eventDate(event)}
                  </p>

                  <p className="mt-1 text-xs text-[#68776C]">
                    {event.location ??
                      event.address ??
                      "Location to be confirmed"}
                  </p>

                  {event.food_description && (
                    <p className="mt-2 text-xs text-[#68776C]">
                      {event.food_description}
                    </p>
                  )}
                </button>

                <button
                  type="button"
                  onClick={() => onTogglePlan(event.id)}
                  className="mt-3 text-xs font-medium text-[#42674A] hover:underline"
                >
                  {planned ? "Remove from My Plan" : "Add to My Plan"}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
