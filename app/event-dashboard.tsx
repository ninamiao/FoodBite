"use client";

import { useEffect, useMemo, useState } from "react";
import {
  displayDate,
  displayLocation,
  displayTime,
  buildCalendarMonth,
  buildCalendarWeek,
  buildWeeklySchedule,
  buildIcsCalendar,
  conditionBadgeLabel,
  conditionLabels,
  getEvidenceDetails,
  foodCostFilterOptions,
  getVisibleEvents,
  getEventDetailSections,
  filterDateGroups,
  foodStatusInfo,
  getEventBadges,
  groupEventsByDate,
  eventsByCalendarDate,
  filterCalendarEvents,
  groupPlannedEvents,
  persistPlannedIds,
  restorePlannedIds,
  sortEvents,
  summarizeIcsExclusions,
  shiftCalendarMonth,
  shiftCalendarWeek,
  type CalendarEventScope,
  type PositionedScheduleEvent,
  type FoodCostFilter,
  type SortMode,
  togglePlannedId,
  type CuratedEvent,
} from "../lib/events";

const PLANNER_STORAGE_KEY = "freebite-planned-event-ids";

function CalendarIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3.5" y="5" width="17" height="15.5" rx="2" /><path d="M7.5 3v4M16.5 3v4M3.5 9.5h17" /></svg>;
}

function ClockIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></svg>;
}

function LocationIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z" /><circle cx="12" cy="10" r="2.2" /></svg>;
}

function CalendarEventRow({ event, planned, onToggle, emphasized = false }: { event: CuratedEvent; planned: boolean; onToggle: (id: string) => void; emphasized?: boolean }) {
  return (
    <article className={`flex flex-col gap-3 rounded-xl border p-4 sm:flex-row sm:items-center sm:justify-between ${emphasized ? "border-[#A9C5AA] bg-[#F1F6EF] shadow-sm" : "border-[#E7EAE3] bg-white"}`}>
      <div className="min-w-0">
        <h4 className="font-semibold">{event.title}</h4>
        <p className="mt-1 text-sm text-[#68776C]">{displayTime(event)} · {displayLocation(event.location)}</p>
        <p className={`mt-2 inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold ${foodStatusInfo[event.food_status].style}`}>{foodStatusInfo[event.food_status].label}</p>
        {planned && <p className="mt-2 text-xs font-semibold text-[#42674A]">In your plan</p>}
      </div>
      <button type="button" onClick={() => onToggle(event.id)} aria-pressed={planned} className={`shrink-0 rounded-lg px-3 py-2 text-sm font-medium ${planned ? "border border-[#DCE5DC] bg-[#F3F6F1] text-[#365B42]" : "bg-[#254A38] text-white hover:bg-[#193B2B]"}`}>
        {planned ? "Remove from plan" : "+ Add to plan"}
      </button>
    </article>
  );
}

function WeeklySchedule({
  weekDates,
  schedule,
  plannedIds,
  onToggle,
}: {
  weekDates: string[];
  schedule: ReturnType<typeof buildWeeklySchedule>;
  plannedIds: Set<string>;
  onToggle: (id: string) => void;
}) {
  const hourLabels = Array.from({ length: 16 }, (_, index) => index + 7);
  const formatDay = (value: string) => new Date(`${value}T00:00:00.000Z`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
  const getBlockStyle = (positioned: PositionedScheduleEvent) => ({
    top: `${positioned.top}px`,
    height: `${positioned.height}px`,
    left: `calc(${(positioned.column * 100) / positioned.columns}% + 2px)`,
    width: `calc(${100 / positioned.columns}% - 4px)`,
  });
  const pxPerHour = 56;
  const scheduleHeight = (22 - 7) * pxPerHour;

  return (
    <div className="overflow-x-auto rounded-xl border border-[#E5E9E2] bg-white">
      <div className="min-w-[980px]">
        <div className="grid grid-cols-[56px_repeat(7,minmax(0,1fr))] border-b border-[#E5E9E2] bg-[#F6F8F4]">
          <div />
          {weekDates.map((date) => <div key={date} className="border-l border-[#E5E9E2] px-2 py-3 text-center text-xs font-semibold text-[#365B42]">{formatDay(date)}</div>)}
        </div>
        <div className="grid grid-cols-[56px_repeat(7,minmax(0,1fr))]">
          <div className="relative text-[10px] text-[#89938A]" style={{ height: scheduleHeight }}>
            {hourLabels.map((hour) => <span key={hour} className="absolute right-2 -translate-y-1/2" style={{ top: `${(hour - 7) * pxPerHour}px` }}>{hour % 12 || 12}{hour < 12 ? " AM" : " PM"}</span>)}
          </div>
          {weekDates.map((date) => (
            <div key={date} className="relative border-l border-[#E5E9E2]" style={{ height: scheduleHeight }}>
              {hourLabels.slice(0, -1).map((hour) => <div key={hour} className="pointer-events-none absolute inset-x-0 border-t border-[#EEF0EB]" style={{ top: `${(hour - 7) * pxPerHour}px` }} />)}
              {(schedule.byDate.get(date) ?? []).map((positioned) => {
                const planned = plannedIds.has(positioned.event.id);
                return <article key={positioned.event.id} style={getBlockStyle(positioned)} title={`${positioned.event.title} · ${displayTime(positioned.event)} · ${displayLocation(positioned.event.location)}`} className={`absolute z-10 overflow-hidden rounded-md p-1.5 text-[10px] leading-tight shadow-sm sm:p-2 ${planned ? "border-2 border-[#557F58] bg-[#DDEBDD] text-[#26482D]" : "border border-[#AFC4AF] bg-[#F1F6EF] text-[#344B3B]"}`}>
                  <p className="line-clamp-2 font-semibold">{positioned.event.title}</p>
                  <p className="mt-1 font-medium">{displayTime(positioned.event)}</p>
                  {positioned.height >= 74 && <p className="mt-1 line-clamp-2 text-[#647467]">{displayLocation(positioned.event.location)}</p>}
                  {positioned.height >= 74 && <button type="button" onClick={() => onToggle(positioned.event.id)} aria-pressed={planned} className="mt-1 rounded bg-white/70 px-1.5 py-0.5 font-semibold hover:bg-white">{planned ? "Remove" : "+ Plan"}</button>}
                  {positioned.height < 74 && <button type="button" onClick={() => onToggle(positioned.event.id)} aria-label={`${planned ? "Remove" : "Add"} ${positioned.event.title} ${planned ? "from" : "to"} plan`} aria-pressed={planned} className="absolute right-1 top-1 rounded bg-white/80 px-1.5 py-0.5 font-semibold">{planned ? "✓" : "+"}</button>}
                </article>;
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const badgeStyles = {
  status: "",
  reason: "bg-slate-100 text-slate-700",
  condition: "bg-amber-50 text-amber-900",
};

function EventCard({
  event,
  planned,
  onToggle,
}: {
  event: CuratedEvent;
  planned: boolean;
  onToggle: (id: string) => void;
}) {
  const badges = getEventBadges(event);
  const foodBadges = badges.filter((badge) => badge.scope === "food");
  const detailSections = getEventDetailSections(event);
  const requirementSections = detailSections.filter((section) => section.kind !== "description");
  const description = detailSections.find((section) => section.kind === "description");

  return (
    <article className="rounded-2xl border border-[#E7EAE3] bg-white p-5 transition hover:border-[#C5D0C5] hover:shadow-sm">
      <h3 className="mt-4 text-lg font-semibold">{event.title}</h3>

      <div className="mt-3 space-y-2 rounded-xl border border-[#E6EBE3] bg-[#F6F8F4] px-3.5 py-3 text-sm text-[#344B3B]">
        <p className="flex items-start gap-2.5 font-semibold"><CalendarIcon /><span>{displayDate(event.date)}</span></p>
        <p className="flex items-start gap-2.5 font-medium"><ClockIcon /><span>{displayTime(event)}</span></p>
        <p className="flex items-start gap-2.5 font-medium"><LocationIcon /><span>{displayLocation(event.location)}{event.address ? <span className="mt-0.5 block text-xs font-normal text-[#68776C]">{event.address}</span> : null}</span></p>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {foodBadges.map((badge) => (
          <span key={`${badge.kind}-${badge.label}`} className={`rounded-full px-3 py-1 text-[11px] font-semibold ${badge.kind === "status" ? foodStatusInfo[event.food_status].style : badgeStyles[badge.kind]}`}>
            {badge.label}
          </span>
        ))}
      </div>

      {event.food_description && (
        <p className="mt-3 text-sm font-medium leading-5 text-[#526157]">{event.food_description}</p>
      )}

      {requirementSections.length > 0 && (
        <div className="mt-3 rounded-xl border border-[#E8E5D8] bg-[#FBFAF5] p-3.5 text-sm text-[#526157]">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#68776C]">Eligibility & participation</h4>
          <div className="space-y-2">
            {requirementSections.map((section, index) => section.kind === "eligibility" ? (
              <p key={`eligibility-${index}`}><span className="font-semibold">Eligibility: </span>{section.text}</p>
            ) : section.kind === "participation" ? (
              <div key={`${section.condition.type}-${index}`}>
                <span className={`inline-flex rounded-full px-3 py-1 text-[11px] font-semibold ${badgeStyles.condition}`}>
                  {conditionBadgeLabel(section.condition)}
                </span>
              </div>
            ) : null)}
          </div>
        </div>
      )}

      {description?.kind === "description" && (
        <p className="mt-3 line-clamp-3 text-sm leading-5 text-[#849087]">{description.text}</p>
      )}

      <details className="mt-4 text-xs text-[#68776C]">
        <summary className="cursor-pointer font-medium">Source, evidence, and review details</summary>
        {event.review_warnings.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-5 text-amber-900">{event.review_warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}</ul>}
        <dl className="mt-3 space-y-2">
          {getEvidenceDetails(event).map(([field, evidence]) => (
            <div key={field}>
              <dt className="font-semibold capitalize">{field.replaceAll("_", " ")}</dt>
              <dd className="mt-0.5">{evidence}</dd>
            </div>
          ))}
        </dl>
        {event.conditions.length > 0 && (
          <div className="mt-4 space-y-2">
            <h4 className="font-semibold">Conditions stated by the source</h4>
            {event.conditions.map((condition, index) => (
              <p key={`${condition.type}-${index}`}>
                <span className="font-medium">{condition.scope === "food" ? "Food: " : "Event: "}{conditionLabels[condition.type]}</span>
                {" — "}{condition.evidence}{" "}<a className="underline" href={condition.source_url} target="_blank" rel="noreferrer">Source</a>
              </p>
            ))}
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
          {event.event_url && <a className="underline" href={event.event_url} target="_blank" rel="noreferrer">Event page</a>}
          <a className="underline" href={event.source_url} target="_blank" rel="noreferrer">Source page</a>
          {event.registration_url && <a className="underline" href={event.registration_url} target="_blank" rel="noreferrer">Registration</a>}
        </div>
      </details>

      <button
        type="button"
        onClick={() => onToggle(event.id)}
        aria-pressed={planned}
        className={`mt-5 w-full rounded-lg py-2.5 text-sm font-medium transition ${
          planned
            ? "border border-[#DCE5DC] bg-[#F3F6F1] text-[#365B42]"
            : "bg-[#254A38] text-white hover:bg-[#193B2B]"
        }`}
      >
        {planned ? "✓ Added to plan" : "+ Add to plan"}
      </button>
    </article>
  );
}

export default function EventDashboard({ events }: { events: CuratedEvent[] }) {
  const [viewMode, setViewMode] = useState<"events" | "calendar">("events");
  const [calendarView, setCalendarView] = useState<"month" | "week">("month");
  const [calendarScope, setCalendarScope] = useState<CalendarEventScope>("all");
  const [calendarMonth, setCalendarMonth] = useState({ year: 2000, month: 1 });
  const [weekAnchor, setWeekAnchor] = useState("2000-01-01");
  
  useEffect(() => {
    const today = new Date();
  
    setCalendarMonth({
      year: today.getFullYear(),
      month: today.getMonth() + 1,
    });
  
    setWeekAnchor(
      `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`
    );
  }, []);
  const [selectedCalendarDate, setSelectedCalendarDate] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("date");
  const [foodCostFilter, setFoodCostFilter] = useState<FoodCostFilter>("all");
  const [browseMode, setBrowseMode] = useState<"all" | "date">("all");
  const [selectedDate, setSelectedDate] = useState("all");
  const [plannedIds, setPlannedIds] = useState<string[]>([]);
  const [plannerLoaded, setPlannerLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let restoredIds: string[] = [];
    try {
      restoredIds = restorePlannedIds(localStorage.getItem(PLANNER_STORAGE_KEY), events);
    } catch {
      // Browser storage may be unavailable; the event list remains usable.
    }
    queueMicrotask(() => {
      if (!cancelled) {
        setPlannedIds(restoredIds);
        setPlannerLoaded(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [events]);

  useEffect(() => {
    if (plannerLoaded) {
      try {
        persistPlannedIds(localStorage, plannedIds);
      } catch {
        // Keep the planner usable for this page session if storage is unavailable.
      }
    }
  }, [plannedIds, plannerLoaded]);

  const plannedSet = useMemo(() => new Set(plannedIds), [plannedIds]);
  const availableEvents = useMemo(
    () => getVisibleEvents(events, search, sortMode, foodCostFilter),
    [events, search, sortMode, foodCostFilter],
  );
  const dateGroups = useMemo(() => groupEventsByDate(availableEvents), [availableEvents]);
  const allDateGroups = useMemo(() => groupEventsByDate(sortEvents(events, sortMode)), [events, sortMode]);
  const visibleGroups = filterDateGroups(dateGroups, selectedDate);
  const plannedEvents = useMemo(
    () => events.filter((event) => plannedSet.has(event.id)),
    [events, plannedSet],
  );
  const groupedPlan = useMemo(() => groupPlannedEvents(plannedEvents), [plannedEvents]);
  const calendarGrid = useMemo(() => buildCalendarMonth(calendarMonth.year, calendarMonth.month), [calendarMonth]);
  const calendarVisibleEvents = useMemo(() => filterCalendarEvents(events, plannedIds, calendarScope), [events, plannedIds, calendarScope]);
  const calendarEvents = useMemo(() => eventsByCalendarDate(calendarVisibleEvents), [calendarVisibleEvents]);
  const weekDates = useMemo(() => buildCalendarWeek(weekAnchor), [weekAnchor]);
  const weeklySchedule = useMemo(() => buildWeeklySchedule(calendarVisibleEvents, weekDates), [calendarVisibleEvents, weekDates]);
  const monthLabel = new Date(Date.UTC(calendarMonth.year, calendarMonth.month - 1, 1)).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
  const weekLabel = `${new Date(`${weekDates[0]}T00:00:00.000Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })} – ${new Date(`${weekDates[6]}T00:00:00.000Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })}`;

  function togglePlan(id: string) {
    setPlannedIds((current) => togglePlannedId(current, id));
  }

  function navigateCalendarMonth(amount: number) {
    setCalendarMonth((current) => shiftCalendarMonth(current.year, current.month, amount));
    setSelectedCalendarDate(null);
  }

  function navigateCalendarWeek(amount: number) {
    setWeekAnchor((current) => shiftCalendarWeek(current, amount));
  }

  function exportPlannerCalendar() {
    const result = buildIcsCalendar(plannedEvents);
    const exclusionSummary = summarizeIcsExclusions(result.excluded);
    if (result.exported.length === 0) {
      setExportMessage(plannedEvents.length === 0
        ? "Your plan is empty. Add an event with a confirmed date, start time, and end time to export."
        : `No calendar file was created. ${result.excluded.length} selected ${result.excluded.length === 1 ? "event was" : "events were"} excluded: ${exclusionSummary}.`);
      return;
    }
    const blob = new Blob([result.content], { type: "text/calendar;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "freebite-events.ics";
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    setExportMessage(result.excluded.length === 0
      ? `Exported ${result.exported.length} ${result.exported.length === 1 ? "event" : "events"}.`
      : `Exported ${result.exported.length}; excluded ${result.excluded.length}: ${exclusionSummary}.`);
  }

  const [exportMessage, setExportMessage] = useState("");

  return (
    <main className="min-h-screen bg-[#F8F9F6] text-[#243B30]">
      <nav className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6">
        <a href="#discover" className="text-2xl font-bold tracking-tight">
          freebite<span className="text-[#D68B60]">.</span>
        </a>
        <div className="flex items-center gap-6 text-sm font-medium">
          <a href="#discover" className="text-[#243B30]">Discover</a>
          <a href="#planner" className="text-[#89938A] hover:text-[#243B30]">Planner</a>
        </div>
      </nav>

      <div className="mx-auto max-w-7xl px-6 pb-20">
        <header className="mb-10 mt-8">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#89958B]">UC San Diego event listings</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">Plan less. Eat better.</h1>
          <p className="mt-3 text-sm text-[#849087]">
            Browse reviewed events. Food details and cost are labeled only when the source supports them.
          </p>
        </header>

        <div className="grid items-start gap-8 lg:grid-cols-[1fr_320px]">
          <section id="discover">
            <div className="mb-5 inline-flex rounded-xl border border-[#E5E9E2] bg-white p-1">
              <button type="button" aria-pressed={viewMode === "events"} onClick={() => setViewMode("events")} className={`rounded-lg px-3 py-2 text-sm ${viewMode === "events" ? "bg-[#254A38] text-white" : "text-[#68776C] hover:bg-[#F6F8F4]"}`}>Events</button>
              <button type="button" aria-pressed={viewMode === "calendar"} onClick={() => setViewMode("calendar")} className={`rounded-lg px-3 py-2 text-sm ${viewMode === "calendar" ? "bg-[#254A38] text-white" : "text-[#68776C] hover:bg-[#F6F8F4]"}`}>Calendar</button>
            </div>

            {viewMode === "events" ? <>
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">Food opportunities</h2>
                <p className="mt-1 text-sm text-[#89938A]">Unconfirmed listings stay visible and clearly labeled.</p>
              </div>
              <span className="text-xs text-[#89938A]">{availableEvents.length} of {events.length} events</span>
            </div>

            <div className="mb-5 flex flex-wrap items-end gap-3">
              <fieldset>
                <legend className="mb-1.5 text-xs font-medium text-[#68776C]">Browse</legend>
                <div className="inline-flex rounded-xl border border-[#E5E9E2] bg-white p-1">
                  <button type="button" aria-pressed={browseMode === "all"} onClick={() => setBrowseMode("all")} className={`rounded-lg px-3 py-2 text-sm ${browseMode === "all" ? "bg-[#254A38] text-white" : "text-[#68776C] hover:bg-[#F6F8F4]"}`}>All events</button>
                  <button type="button" aria-pressed={browseMode === "date"} onClick={() => setBrowseMode("date")} className={`rounded-lg px-3 py-2 text-sm ${browseMode === "date" ? "bg-[#254A38] text-white" : "text-[#68776C] hover:bg-[#F6F8F4]"}`}>By date</button>
                </div>
              </fieldset>

              {browseMode === "date" && (
                <label className="min-w-48 flex-1 sm:flex-none">
                  <span className="mb-1.5 block text-xs font-medium text-[#68776C]">Select a date</span>
                  <select value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} className="w-full rounded-xl border border-[#E5E9E2] bg-white px-3 py-2.5 text-sm text-[#243B30]">
                    <option value="all">All dates</option>
                    {allDateGroups.dated.map(({ date }) => <option key={date} value={date}>{displayDate(date)}</option>)}
                    {allDateGroups.undated.length > 0 && <option value="__undated__">Date to be confirmed</option>}
                  </select>
                </label>
              )}

              <label className="min-w-52 flex-1 sm:flex-none">
                <span className="mb-1.5 block text-xs font-medium text-[#68776C]">Sort</span>
                <select value={sortMode} onChange={(event) => setSortMode(event.target.value as SortMode)} className="w-full rounded-xl border border-[#E5E9E2] bg-white px-3 py-2.5 text-sm text-[#243B30]">
                  <option value="date">Date: earliest first</option>
                  <option value="food">Confirmed food first</option>
                </select>
              </label>

              <label className="min-w-52 flex-1 sm:flex-none">
                <span className="mb-1.5 block text-xs font-medium text-[#68776C]">Food cost</span>
                <select value={foodCostFilter} onChange={(event) => setFoodCostFilter(event.target.value as FoodCostFilter)} className="w-full rounded-xl border border-[#E5E9E2] bg-white px-3 py-2.5 text-sm text-[#243B30]">
                  {foodCostFilterOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
            </div>

            <label className="mb-5 block">
              <span className="sr-only">Search events</span>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search events, food, dates, or locations..."
                className="w-full rounded-xl border border-[#E5E9E2] bg-white px-4 py-3 text-sm outline-none transition focus:border-[#567B60]"
              />
            </label>

            {availableEvents.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-[#DCE3D9] bg-white p-8 text-center text-sm text-[#68776C]">
                No events match “{search}”. Try a title, food, date, or location term.
              </p>
            ) : browseMode === "all" ? (
              <div className="grid gap-4 sm:grid-cols-2">
                {availableEvents.map((event) => <EventCard key={event.id} event={event} planned={plannedSet.has(event.id)} onToggle={togglePlan} />)}
              </div>
            ) : (
              <div className="space-y-8">
                {visibleGroups.dated.map(({ date, events: groupedEvents }) => (
                  <section key={date} aria-label={`Events on ${displayDate(date)}`}>
                    <h3 className="mb-3 border-b border-[#E3E8E0] pb-2 text-sm font-semibold text-[#365B42]">{displayDate(date)}</h3>
                    <div className="grid gap-4 sm:grid-cols-2">
                      {groupedEvents.map((event) => <EventCard key={event.id} event={event} planned={plannedSet.has(event.id)} onToggle={togglePlan} />)}
                    </div>
                  </section>
                ))}
                {visibleGroups.undated.length > 0 && (
                  <section aria-label="Events with date to be confirmed">
                    <h3 className="mb-3 border-b border-[#E3E8E0] pb-2 text-sm font-semibold text-[#68776C]">Date to be confirmed</h3>
                    <div className="grid gap-4 sm:grid-cols-2">
                      {visibleGroups.undated.map((event) => <EventCard key={event.id} event={event} planned={plannedSet.has(event.id)} onToggle={togglePlan} />)}
                    </div>
                  </section>
                )}
                {selectedDate !== "all" && selectedDate !== "__undated__" && visibleGroups.dated.length === 0 && (
                  <p className="rounded-2xl border border-dashed border-[#DCE3D9] bg-white p-8 text-center text-sm text-[#68776C]">No events are available for this date.</p>
                )}
                {selectedDate === "__undated__" && visibleGroups.undated.length === 0 && (
                  <p className="rounded-2xl border border-dashed border-[#DCE3D9] bg-white p-8 text-center text-sm text-[#68776C]">No events have an unknown date.</p>
                )}
              </div>
            )}
            </> : (
              <div>
                <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
                  <fieldset>
                    <legend className="mb-1.5 text-xs font-medium text-[#68776C]">Calendar events</legend>
                    <div className="inline-flex rounded-xl border border-[#E5E9E2] bg-white p-1">
                      <button type="button" aria-pressed={calendarScope === "all"} onClick={() => setCalendarScope("all")} className={`rounded-lg px-3 py-2 text-sm ${calendarScope === "all" ? "bg-[#254A38] text-white" : "text-[#68776C] hover:bg-[#F6F8F4]"}`}>All Events</button>
                      <button type="button" aria-pressed={calendarScope === "planned"} onClick={() => setCalendarScope("planned")} className={`rounded-lg px-3 py-2 text-sm ${calendarScope === "planned" ? "bg-[#254A38] text-white" : "text-[#68776C] hover:bg-[#F6F8F4]"}`}>My Plan</button>
                    </div>
                  </fieldset>
                  <fieldset>
                    <legend className="mb-1.5 text-xs font-medium text-[#68776C]">Calendar view</legend>
                    <div className="inline-flex rounded-xl border border-[#E5E9E2] bg-white p-1">
                      <button type="button" aria-pressed={calendarView === "month"} onClick={() => setCalendarView("month")} className={`rounded-lg px-3 py-2 text-sm ${calendarView === "month" ? "bg-[#254A38] text-white" : "text-[#68776C] hover:bg-[#F6F8F4]"}`}>Month</button>
                      <button type="button" aria-pressed={calendarView === "week"} onClick={() => setCalendarView("week")} className={`rounded-lg px-3 py-2 text-sm ${calendarView === "week" ? "bg-[#254A38] text-white" : "text-[#68776C] hover:bg-[#F6F8F4]"}`}>Week</button>
                    </div>
                  </fieldset>
                </div>

                {calendarScope === "planned" && plannedEvents.length === 0 && <p className="mb-4 rounded-xl border border-dashed border-[#DCE3D9] bg-white p-4 text-sm text-[#68776C]">Your plan is empty. Add an event from the Events view or All Events calendar.</p>}

                <div className="mb-4 flex items-center justify-between gap-3">
                  <button type="button" onClick={() => calendarView === "month" ? navigateCalendarMonth(-1) : navigateCalendarWeek(-1)} aria-label={calendarView === "month" ? "Previous month" : "Previous week"} className="rounded-lg border border-[#E5E9E2] bg-white px-3 py-2 text-sm text-[#365B42] hover:bg-[#F6F8F4]">← Previous {calendarView}</button>
                  <h2 className="text-center text-xl font-semibold" aria-live="polite">{calendarView === "month" ? monthLabel : weekLabel}</h2>
                  <button type="button" onClick={() => calendarView === "month" ? navigateCalendarMonth(1) : navigateCalendarWeek(1)} aria-label={calendarView === "month" ? "Next month" : "Next week"} className="rounded-lg border border-[#E5E9E2] bg-white px-3 py-2 text-sm text-[#365B42] hover:bg-[#F6F8F4]">Next {calendarView} →</button>
                </div>

                {calendarView === "month" ? <>
                  <div className="overflow-hidden rounded-2xl border border-[#E5E9E2] bg-white">
                    <div className="grid grid-cols-7 border-b border-[#E5E9E2] bg-[#F6F8F4] text-center text-xs font-semibold text-[#68776C]">
                      {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => <div key={day} className="py-2">{day}</div>)}
                    </div>
                    <div className="grid grid-cols-7">
                      {calendarGrid.weeks.flat().map((day) => {
                        const dayEvents = calendarEvents.dated.get(day.date) ?? [];
                        const plannedCount = dayEvents.filter((event) => plannedSet.has(event.id)).length;
                        const selected = selectedCalendarDate === day.date;
                        return <button key={day.date} type="button" aria-label={`${day.date}${dayEvents.length ? `, ${dayEvents.length} ${dayEvents.length === 1 ? "event" : "events"}` : ", no events"}`} aria-pressed={selected} onClick={() => { setSelectedCalendarDate(day.date); if (!day.inMonth) { const [year, month] = day.date.split("-").map(Number); setCalendarMonth({ year, month }); } }} className={`min-h-16 border-b border-r border-[#EEF0EB] p-1.5 text-left sm:min-h-20 sm:p-2 ${day.inMonth ? "text-[#243B30]" : "bg-[#FBFCFA] text-[#ADB5AE]"} ${selected ? "ring-2 ring-inset ring-[#567B60]" : "hover:bg-[#F6F8F4]"}`}>
                          <span className="text-xs font-medium sm:text-sm">{day.day}</span>
                          {dayEvents.length > 0 && <span className="mt-1 flex flex-wrap items-center gap-x-1 gap-y-0.5 text-[10px] font-semibold text-[#42674A] sm:text-xs"><span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-[#6A926B]" />{dayEvents.length} <span className="hidden sm:inline">{dayEvents.length === 1 ? "event" : "events"}</span>{calendarScope === "all" && plannedCount > 0 && <span className="rounded bg-[#DDEBDD] px-1 text-[#26482D]">{plannedCount} planned</span>}</span>}
                        </button>;
                      })}
                    </div>
                  </div>
                  <section className="mt-6" aria-live="polite">
                    <h3 className="mb-3 text-base font-semibold">{selectedCalendarDate ? displayDate(selectedCalendarDate) : "Select a date"}</h3>
                    {selectedCalendarDate ? (
                      (calendarEvents.dated.get(selectedCalendarDate) ?? []).length > 0 ? <div className="space-y-3">{calendarEvents.dated.get(selectedCalendarDate)!.map((event) => <CalendarEventRow key={event.id} event={event} planned={plannedSet.has(event.id)} onToggle={togglePlan} emphasized={plannedSet.has(event.id)} />)}</div> : <p className="rounded-xl border border-dashed border-[#DCE3D9] bg-white p-5 text-sm text-[#68776C]">No events on this date.</p>
                    ) : <p className="text-sm text-[#89938A]">Choose a calendar date to see its events.</p>}
                  </section>
                </> : <>
                  <WeeklySchedule weekDates={weekDates} schedule={weeklySchedule} plannedIds={plannedSet} onToggle={togglePlan} />
                  {calendarVisibleEvents.length === 0 && <p className="mt-4 text-sm text-[#68776C]">No events are in this calendar view.</p>}
                  {weeklySchedule.untimed.length > 0 && <section className="mt-6" aria-label="Events with time to be confirmed">
                    <h3 className="mb-3 border-b border-[#E3E8E0] pb-2 text-sm font-semibold text-[#68776C]">Time to be confirmed this week</h3>
                    <div className="space-y-3">{weeklySchedule.untimed.map((event) => <CalendarEventRow key={event.id} event={event} planned={plannedSet.has(event.id)} onToggle={togglePlan} emphasized={plannedSet.has(event.id)} />)}</div>
                  </section>}
                  {weeklySchedule.outsideHours.length > 0 && <section className="mt-6" aria-label="Events outside displayed hours">
                    <h3 className="mb-3 border-b border-[#E3E8E0] pb-2 text-sm font-semibold text-[#68776C]">Outside displayed hours (7 AM–10 PM)</h3>
                    <div className="space-y-3">{weeklySchedule.outsideHours.map((event) => <CalendarEventRow key={event.id} event={event} planned={plannedSet.has(event.id)} onToggle={togglePlan} emphasized={plannedSet.has(event.id)} />)}</div>
                  </section>}
                </>}

                {calendarEvents.undated.length > 0 && <section className="mt-8" aria-label="Events with date to be confirmed">
                  <h3 className="mb-3 border-b border-[#E3E8E0] pb-2 text-sm font-semibold text-[#68776C]">Date to be confirmed</h3>
                  <div className="space-y-3">{calendarEvents.undated.map((event) => <CalendarEventRow key={event.id} event={event} planned={plannedSet.has(event.id)} onToggle={togglePlan} emphasized={plannedSet.has(event.id)} />)}</div>
                </section>}
              </div>
            )}
          </section>

          <aside id="planner" className="rounded-2xl border border-[#E7EAE3] bg-white p-5 lg:sticky lg:top-6">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">My plan</h2>
              <span className="rounded-full bg-[#EDF3EC] px-2.5 py-1 text-xs font-semibold text-[#42674A]">
                {plannedEvents.length} saved
              </span>
            </div>
            <p className="mt-2 text-sm text-[#89938A]">Your selections, grouped by confirmed date.</p>

            <button type="button" onClick={exportPlannerCalendar} className="mt-4 w-full rounded-lg border border-[#DCE5DC] bg-[#F3F6F1] px-3 py-2.5 text-sm font-medium text-[#365B42] transition hover:bg-[#EAF0E8]">Export to Calendar</button>
            {exportMessage && <p role="status" aria-live="polite" className="mt-2 text-xs leading-5 text-[#68776C]">{exportMessage}</p>}

            {plannedEvents.length === 0 ? (
              <div className="mt-5 rounded-xl border border-dashed border-[#DCE3D9] px-4 py-8 text-center">
                <p className="text-sm font-medium">Nothing planned yet</p>
                <p className="mt-2 text-xs leading-5 text-[#929D94]">Add an event to organize your plan.</p>
              </div>
            ) : (
              <div className="mt-5 space-y-6">
                {groupedPlan.dated.map(({ date, events: dayEvents }) => (
                  <section key={date}>
                    <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#89938A]">{displayDate(date)}</h3>
                    <div className="space-y-3">
                      {dayEvents.map((event) => (
                        <div key={event.id} className="rounded-xl bg-[#F6F8F4] p-4">
                          <span className="text-xs font-medium text-[#66806A]">{displayTime(event)}</span>
                          <h4 className="mt-2 text-sm font-semibold">{event.title}</h4>
                          <p className="mt-1 text-xs text-[#89938A]">{displayLocation(event.location)}</p>
                          <button type="button" onClick={() => togglePlan(event.id)} className="mt-3 text-xs font-medium text-[#A46A51] hover:underline">Remove</button>
                        </div>
                      ))}
                    </div>
                  </section>
                ))}

                {groupedPlan.undated.length > 0 && (
                  <section>
                    <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#89938A]">Date to be confirmed</h3>
                    <div className="space-y-3">
                      {groupedPlan.undated.map((event) => (
                        <div key={event.id} className="rounded-xl bg-[#F6F8F4] p-4">
                          <span className="text-xs font-medium text-[#66806A]">{displayTime(event)}</span>
                          <h4 className="mt-2 text-sm font-semibold">{event.title}</h4>
                          <p className="mt-1 text-xs text-[#89938A]">{displayLocation(event.location)}</p>
                          <button type="button" onClick={() => togglePlan(event.id)} className="mt-3 text-xs font-medium text-[#A46A51] hover:underline">Remove</button>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            )}

            <div className="mt-6 border-t border-[#EEF0EB] pt-4">
              <p className="text-xs leading-5 text-[#929D94]">Your plan is saved in this browser. Events without confirmed dates stay separate.</p>
            </div>
          </aside>
        </div>
      </div>

      <footer className="border-t border-[#E7EAE3] px-6 py-7 text-center text-xs text-[#9AA39B]">
        FreeBite · Find good food, not expensive food.
      </footer>
    </main>
  );
}
