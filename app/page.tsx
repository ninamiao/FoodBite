import eventData from "../data/events.json";
import EventDashboard from "./event-dashboard";
import type { EventDataset } from "../lib/events";

const dataset = eventData as EventDataset;

export default function Home() {
  return <EventDashboard events={dataset.events} />;
}
