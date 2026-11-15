export type FoodStatus =
  | "confirmed_free"
  | "provided_cost_unknown"
  | "food_unconfirmed"
  | "not_provided";

export type EventEvidence = {
  title: string | null;
  date: string | null;
  time: string | null;
  location: string | null;
  provides_food: string | null;
  is_free: string | null;
  food_description: string | null;
  eligibility: string | null;
  address?: string | null;
};

export type EventCondition = {
  type:
    | "limited_quantity"
    | "first_come_first_served"
    | "rsvp_required"
    | "eligibility_required"
    | "event_participants_only"
    | "purchase_required";
  scope: "food" | "event";
  evidence: string;
  source_url: string;
};

export type CuratedEvent = {
  id: string;
  title: string;
  original_title: string;
  description: string | null;
  date: string | null;
  start_time: string | null;
  end_time: string | null;
  location: string | null;
  address: string | null;
  food_description: string | null;
  eligibility: string | null;
  registration_url: string | null;
  event_url: string | null;
  source_url: string;
  evidence: EventEvidence;
  extraction_evidence: EventEvidence;
  food_status: FoodStatus;
  review_warnings: string[];
  conditions: EventCondition[];
};

export type EventDataset = {
  schema_version: string;
  source_run: string;
  reviewed_at: string;
  exclusions_file: string;
  events: CuratedEvent[];
};

export type CalendarDay = { date: string; day: number; inMonth: boolean };
export type CalendarMonth = { year: number; month: number; weeks: CalendarDay[][] };
export type CalendarEventScope = "all" | "planned";
export type PositionedScheduleEvent = {
  event: CuratedEvent;
  top: number;
  height: number;
  column: number;
  columns: number;
};

export function filterCalendarEvents(events: CuratedEvent[], plannedIds: string[], scope: CalendarEventScope): CuratedEvent[] {
  if (scope === "all") return events;
  const planned = new Set(plannedIds);
  return events.filter((event) => planned.has(event.id));
}

export function shiftCalendarMonth(year: number, month: number, amount: number): { year: number; month: number } {
  const shifted = new Date(Date.UTC(year, month - 1 + amount, 1));
  return { year: shifted.getUTCFullYear(), month: shifted.getUTCMonth() + 1 };
}

export function buildCalendarMonth(year: number, month: number): CalendarMonth {
  if (!Number.isInteger(month) || month < 1 || month > 12) throw new RangeError("month must be between 1 and 12");
  const first = new Date(Date.UTC(year, month - 1, 1));
  const mondayOffset = (first.getUTCDay() + 6) % 7;
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const cellCount = Math.ceil((mondayOffset + lastDay) / 7) * 7;
  const days = Array.from({ length: cellCount }, (_, index): CalendarDay => {
    const date = new Date(Date.UTC(year, month - 1, index - mondayOffset + 1));
    return {
      date: date.toISOString().slice(0, 10),
      day: date.getUTCDate(),
      inMonth: date.getUTCMonth() === month - 1,
    };
  });
  const weeks: CalendarDay[][] = [];
  for (let index = 0; index < days.length; index += 7) weeks.push(days.slice(index, index + 7));
  return { year, month, weeks };
}

export function eventsByCalendarDate(events: CuratedEvent[]): { dated: Map<string, CuratedEvent[]>; undated: CuratedEvent[] } {
  const dated = new Map<string, CuratedEvent[]>();
  const undated: CuratedEvent[] = [];
  for (const event of events) {
    if (!event.date) {
      undated.push(event);
      continue;
    }
    const current = dated.get(event.date) ?? [];
    current.push(event);
    dated.set(event.date, current);
  }
  return { dated, undated };
}

function parseCalendarDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return parsed.toISOString().slice(0, 10) === value ? parsed : null;
}

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function buildCalendarWeek(anchorDate: string): string[] {
  const anchor = parseCalendarDate(anchorDate);
  if (!anchor) throw new RangeError("anchorDate must be a valid YYYY-MM-DD date");
  const mondayOffset = (anchor.getUTCDay() + 6) % 7;
  const monday = new Date(anchor);
  monday.setUTCDate(anchor.getUTCDate() - mondayOffset);
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(monday);
    date.setUTCDate(monday.getUTCDate() + index);
    return isoDate(date);
  });
}

export function shiftCalendarWeek(anchorDate: string, amount: number): string {
  const week = buildCalendarWeek(anchorDate);
  const shifted = new Date(`${week[0]}T00:00:00.000Z`);
  shifted.setUTCDate(shifted.getUTCDate() + amount * 7);
  return isoDate(shifted);
}

export function buildWeeklySchedule(
  events: CuratedEvent[],
  weekDates: string[],
  startHour = 7,
  endHour = 22,
  pixelsPerHour = 56,
): { byDate: Map<string, PositionedScheduleEvent[]>; untimed: CuratedEvent[]; outsideHours: CuratedEvent[] } {
  const byDate = new Map<string, PositionedScheduleEvent[]>();
  const untimed: CuratedEvent[] = [];
  const outsideHours: CuratedEvent[] = [];
  const weekDateSet = new Set(weekDates);
  const startOfDay = startHour * 60;
  const endOfDay = endHour * 60;

  for (const event of events) {
    if (!event.date || !weekDateSet.has(event.date)) continue;
    const startMatch = event.start_time?.match(/^(\d{2}):(\d{2})$/);
    const endMatch = event.end_time?.match(/^(\d{2}):(\d{2})$/);
    if (!startMatch || !endMatch) {
      untimed.push(event);
      continue;
    }
    const start = Number(startMatch[1]) * 60 + Number(startMatch[2]);
    const end = Number(endMatch[1]) * 60 + Number(endMatch[2]);
    if (Number(startMatch[1]) > 23 || Number(startMatch[2]) > 59 || Number(endMatch[1]) > 23 || Number(endMatch[2]) > 59 || end <= start) {
      untimed.push(event);
      continue;
    }
    const clippedStart = Math.max(start, startOfDay);
    const clippedEnd = Math.min(end, endOfDay);
    if (clippedStart >= clippedEnd) {
      outsideHours.push(event);
      continue;
    }
    const dayEvents = byDate.get(event.date) ?? [];
    dayEvents.push({
      event,
      top: ((clippedStart - startOfDay) / 60) * pixelsPerHour,
      height: ((clippedEnd - clippedStart) / 60) * pixelsPerHour,
      column: 0,
      columns: 1,
    });
    byDate.set(event.date, dayEvents);
  }

  for (const [date, dayEvents] of byDate) {
    dayEvents.sort((a, b) => a.top - b.top || a.event.end_time!.localeCompare(b.event.end_time!));
    let cluster: PositionedScheduleEvent[] = [];
    let clusterEnd = -1;
    const placeCluster = () => {
      if (cluster.length === 0) return;
      const columnEnds: number[] = [];
      for (const positioned of cluster) {
        const start = positioned.top;
        const end = positioned.top + positioned.height;
        let column = columnEnds.findIndex((columnEnd) => columnEnd <= start);
        if (column < 0) column = columnEnds.length;
        columnEnds[column] = end;
        positioned.column = column;
      }
      for (const positioned of cluster) positioned.columns = columnEnds.length;
      cluster = [];
      clusterEnd = -1;
    };
    for (const positioned of dayEvents) {
      const end = positioned.top + positioned.height;
      if (cluster.length > 0 && positioned.top >= clusterEnd) placeCluster();
      cluster.push(positioned);
      clusterEnd = Math.max(clusterEnd, end);
    }
    placeCluster();
    byDate.set(date, dayEvents);
  }
  return { byDate, untimed, outsideHours };
}

export type IcsExcludedEvent = { event: CuratedEvent; reason: string };
export type IcsCalendarResult = { content: string; exported: CuratedEvent[]; excluded: IcsExcludedEvent[] };

export function summarizeIcsExclusions(excluded: IcsExcludedEvent[]): string {
  const counts = new Map<string, number>();
  for (const item of excluded) counts.set(item.reason, (counts.get(item.reason) ?? 0) + 1);
  return [...counts.entries()].map(([reason, count]) => `${count} ${reason}`).join("; ");
}

export function escapeIcsText(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/\r\n|\r|\n/g, "\\n")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;");
}

function validIsoDate(value: string | null): value is string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}

function validIsoTime(value: string | null): value is string {
  return value !== null && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value);
}

function foldIcsLine(line: string): string {
  const chunks: string[] = [];
  let current = "";
  let bytes = 0;
  for (const character of line) {
    const width = new TextEncoder().encode(character).length;
    if (bytes + width > 75) {
      chunks.push(current);
      current = ` ${character}`;
      bytes = 1 + width;
    } else {
      current += character;
      bytes += width;
    }
  }
  chunks.push(current);
  return chunks.join("\r\n");
}

function icsDateTime(date: string, time: string): string {
  return `${date.replaceAll("-", "")}T${time.replace(":", "")}00`;
}

export function buildIcsCalendar(events: CuratedEvent[], timestamp = new Date()): IcsCalendarResult {
  const exported: CuratedEvent[] = [];
  const excluded: IcsExcludedEvent[] = [];
  for (const event of events) {
    if (!validIsoDate(event.date)) {
      excluded.push({ event, reason: "no confirmed date" });
    } else if (!validIsoTime(event.start_time) || !validIsoTime(event.end_time)) {
      excluded.push({ event, reason: "confirmed start and end times are required" });
    } else if (event.end_time <= event.start_time) {
      excluded.push({ event, reason: "end time is not after start time on the confirmed date" });
    } else {
      exported.push(event);
    }
  }

  const stamp = timestamp.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FreeBite//Food Events//EN", "CALSCALE:GREGORIAN"];
  for (const event of exported) {
    lines.push(
      "BEGIN:VEVENT",
      `UID:${event.id}@freebite.local`,
      `DTSTAMP:${stamp}`,
      `DTSTART:${icsDateTime(event.date!, event.start_time!)}`,
      `DTEND:${icsDateTime(event.date!, event.end_time!)}`,
      `SUMMARY:${escapeIcsText(event.title)}`,
    );
    if (event.description) lines.push(`DESCRIPTION:${escapeIcsText(event.description)}`);
    const location = [event.location, event.address].filter((part): part is string => Boolean(part)).join(", ");
    if (location) lines.push(`LOCATION:${escapeIcsText(location)}`);
    if (event.source_url) lines.push(`URL:${event.source_url.replace(/[\r\n]/g, "")}`);
    lines.push("END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return { content: `${lines.map(foldIcsLine).join("\r\n")}\r\n`, exported, excluded };
}

export const foodStatusInfo: Record<FoodStatus, { label: string; style: string }> = {
  confirmed_free: {
    label: "Confirmed free food",
    style: "bg-emerald-50 text-emerald-700",
  },
  provided_cost_unknown: {
    label: "Food provided · cost unknown",
    style: "bg-amber-50 text-amber-800",
  },
  food_unconfirmed: {
    label: "Food unconfirmed",
    style: "bg-gray-100 text-gray-700",
  },
  not_provided: {
    label: "Food not provided",
    style: "bg-gray-100 text-gray-600",
  },
};

const foodSearchTerms = [
  "food", "meal", "meals", "snack", "snacks", "pastry", "pastries", "pizza",
  "boba", "drink", "drinks", "beverage", "beverages", "coffee", "tea", "juice",
  "hot chocolate", "chocolate", "pan dulce", "refreshments", "produce", "fruit",
  "sandwich", "sandwiches", "taco", "tacos", "doughnut", "donut", "cookies",
  "bread", "cocoa",
];

const drinkSearchTerms = [
  "drink", "drinks", "beverage", "beverages", "boba", "coffee", "tea", "juice",
  "hot chocolate", "cocoa", "water", "smoothie", "smoothies",
];

const searchAliases: Record<string, string[]> = {
  food: foodSearchTerms,
  foods: foodSearchTerms,
  eat: foodSearchTerms,
  meal: ["meal", "meals", "dinner", "food"],
  meals: ["meal", "meals", "dinner", "food"],
  drink: drinkSearchTerms,
  drinks: drinkSearchTerms,
  beverage: drinkSearchTerms,
  beverages: drinkSearchTerms,
  snack: ["snack", "snacks", "refreshments", "pan dulce", "pastry", "pastries", "cookies", "chips"],
  snacks: ["snack", "snacks", "refreshments", "pan dulce", "pastry", "pastries", "cookies", "chips"],
  pastry: ["pastry", "pastries", "baked goods", "bakery"],
  pastries: ["pastry", "pastries", "baked goods", "bakery"],
  sweet: ["sweet", "dessert", "pastry", "pastries", "boba", "cookies", "chocolate"],
};

function containsSearchTerm(text: string, term: string): boolean {
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:^|[^a-z0-9])${escaped}(?=$|[^a-z0-9])`, "i").test(text);
}

function searchableContent(values: Array<string | null>): string {
  return values
    .filter((value): value is string => Boolean(value))
    .join(" ")
    .replace(/food details are not confirmed by the source/gi, " ")
    .replace(/food information has not been confirmed/gi, " ")
    .replace(/food cost remains unconfirmed/gi, " ")
    .replace(/(?:date|time|location)\s+(?:to be confirmed|tba)/gi, " ")
    .replace(/food (?:not confirmed|unconfirmed)/gi, " ")
    .replace(/extraction is_free[^.]*\.?/gi, " ")
    .toLocaleLowerCase();
}

export function searchEvents(events: CuratedEvent[], query: string): CuratedEvent[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  if (!normalizedQuery) return events;

  const alternatives = searchAliases[normalizedQuery] ?? [normalizedQuery];
  return events.filter((event) => {
    const searchableText = searchableContent([
      event.title,
      event.description,
      event.food_description,
      event.location,
      event.address,
      event.date,
    ]);

    return alternatives.some((term) => containsSearchTerm(searchableText, term));
  });
}

export type SortMode = "date" | "food";
export type FoodCostFilter = "all" | "confirmed_free" | "not_confirmed_free";

export const foodCostFilterOptions: Array<{ value: FoodCostFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "confirmed_free", label: "Confirmed free" },
  { value: "not_confirmed_free", label: "Not confirmed free" },
];

export function filterEventsByFoodCost(events: CuratedEvent[], filter: FoodCostFilter): CuratedEvent[] {
  if (filter === "all") return events;
  if (filter === "confirmed_free") return events.filter((event) => event.food_status === "confirmed_free");
  return events.filter((event) => event.food_status !== "confirmed_free");
}

const foodStatusPriority: Record<FoodStatus, number> = {
  confirmed_free: 0,
  provided_cost_unknown: 1,
  food_unconfirmed: 2,
  not_provided: 3,
};

export function sortEvents(events: CuratedEvent[], mode: SortMode): CuratedEvent[] {
  return events
    .map((event, index) => ({ event, index }))
    .sort((a, b) => {
      if (mode === "food") {
        const priorityDifference = foodStatusPriority[a.event.food_status] - foodStatusPriority[b.event.food_status];
        if (priorityDifference !== 0) return priorityDifference;
      }
      if (a.event.date === null) return b.event.date === null ? a.index - b.index : 1;
      if (b.event.date === null) return -1;
      return a.event.date.localeCompare(b.event.date) || a.index - b.index;
    })
    .map(({ event }) => event);
}

export function getVisibleEvents(
  events: CuratedEvent[],
  query: string,
  sortMode: SortMode,
  foodCostFilter: FoodCostFilter,
): CuratedEvent[] {
  return sortEvents(filterEventsByFoodCost(searchEvents(events, query), foodCostFilter), sortMode);
}

export function groupEventsByDate(events: CuratedEvent[]) {
  const dated = new Map<string, CuratedEvent[]>();
  const undated: CuratedEvent[] = [];
  for (const event of events) {
    if (event.date === null) {
      undated.push(event);
    } else {
      const group = dated.get(event.date) ?? [];
      group.push(event);
      dated.set(event.date, group);
    }
  }
  return {
    dated: [...dated.entries()]
      .sort(([dateA], [dateB]) => dateA.localeCompare(dateB))
      .map(([date, group]) => ({ date, events: group })),
    undated,
  };
}

export function filterDateGroups(
  groups: ReturnType<typeof groupEventsByDate>,
  selectedDate: string,
) {
  if (selectedDate === "all") return groups;
  if (selectedDate === "__undated__") return { dated: [], undated: groups.undated };
  return { dated: groups.dated.filter((group) => group.date === selectedDate), undated: [] };
}

export type EventBadge = {
  label: string;
  kind: "status" | "reason" | "condition";
  scope: "food" | "event";
};

export type EventDetailSection =
  | { kind: "eligibility"; text: string }
  | { kind: "participation"; condition: EventCondition }
  | { kind: "description"; text: string };

export function getEventDetailSections(event: CuratedEvent): EventDetailSection[] {
  const sections: EventDetailSection[] = [];
  if (event.eligibility?.trim()) sections.push({ kind: "eligibility", text: event.eligibility });
  for (const condition of event.conditions) {
    if (condition.scope === "event") sections.push({ kind: "participation", condition });
  }
  if (event.description?.trim()) sections.push({ kind: "description", text: event.description });
  return sections;
}

export function getEvidenceDetails(event: CuratedEvent): Array<[string, string]> {
  return Object.entries(event.evidence).filter((entry) =>
    Boolean(entry[1]) && !event.conditions.some((condition) => condition.evidence === entry[1]),
  ) as Array<[string, string]>;
}

export const conditionLabels: Record<EventCondition["type"], string> = {
  limited_quantity: "Limited quantity",
  first_come_first_served: "First come, first served",
  rsvp_required: "RSVP required",
  eligibility_required: "Eligibility required",
  event_participants_only: "Event participants only",
  purchase_required: "Purchase required",
};

export function conditionBadgeLabel(condition: EventCondition): string {
  return condition.scope === "event" && condition.type === "rsvp_required"
    ? "Event registration required"
    : conditionLabels[condition.type];
}

export function getEventBadges(event: CuratedEvent): EventBadge[] {
  const badges: EventBadge[] = [
    { label: foodStatusInfo[event.food_status].label, kind: "status", scope: "food" },
  ];
  const freeEvidence = event.evidence.is_free ?? "";
  const explicitlyFreeAdmission = /admission|free event|free and open|free public|public forum|our events are free|free for .{0,60}(?:students|the public)/i.test(freeEvidence);
  if (event.food_status !== "confirmed_free" && explicitlyFreeAdmission) {
    badges.push({ label: "Admission ≠ free food", kind: "reason", scope: "food" });
  }
  for (const condition of event.conditions) {
    const label = conditionBadgeLabel(condition);
    if (!badges.some((badge) => badge.label === label)) {
      badges.push({ label, kind: "condition", scope: condition.scope });
    }
  }
  return badges;
}

export function sortByConfirmedTime(events: CuratedEvent[]): CuratedEvent[] {
  return [...events].sort((a, b) => {
    if (a.start_time === null) return b.start_time === null ? a.title.localeCompare(b.title) : 1;
    if (b.start_time === null) return -1;
    return a.start_time.localeCompare(b.start_time) || a.title.localeCompare(b.title);
  });
}

export function groupPlannedEvents(events: CuratedEvent[]) {
  const dated = new Map<string, CuratedEvent[]>();
  const undated: CuratedEvent[] = [];

  for (const event of events) {
    if (event.date === null) {
      undated.push(event);
      continue;
    }
    const group = dated.get(event.date) ?? [];
    group.push(event);
    dated.set(event.date, group);
  }

  return {
    dated: [...dated.entries()]
      .sort(([dateA], [dateB]) => dateA.localeCompare(dateB))
      .map(([date, group]) => ({ date, events: sortByConfirmedTime(group) })),
    undated: sortByConfirmedTime(undated),
  };
}

export function togglePlannedId(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((plannedId) => plannedId !== id) : [...ids, id];
}

export function displayTime(event: CuratedEvent): string {
  if (event.start_time && event.end_time) return `${event.start_time}–${event.end_time}`;
  if (event.start_time) return `Starts ${event.start_time}`;
  if (event.end_time) return `Ends ${event.end_time}`;
  return "Time TBA";
}

export function displayDate(date: string | null): string {
  if (date === null) return "Date TBA";
  const [year, month, day] = date.split("-").map(Number);
  return new Date(year, month - 1, day, 12).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function displayLocation(location: string | null): string {
  return location ?? "Location TBA";
}

export function restorePlannedIds(value: string | null, events: CuratedEvent[]): string[] {
  if (value === null) return [];
  try {
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    const validIds = new Set(events.map((event) => event.id));
    return parsed.filter((id): id is string => typeof id === "string" && validIds.has(id));
  } catch {
    return [];
  }
}

export function persistPlannedIds(storage: Pick<Storage, "setItem">, ids: string[]): void {
  storage.setItem("freebite-planned-event-ids", JSON.stringify(ids));
}
