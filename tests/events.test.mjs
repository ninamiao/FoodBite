import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  buildCalendarMonth,
  buildCalendarWeek,
  buildWeeklySchedule,
  buildIcsCalendar,
  displayDate,
  displayLocation,
  displayTime,
  eventsByCalendarDate,
  filterCalendarEvents,
  filterEventsByFoodCost,
  filterDateGroups,
  foodCostFilterOptions,
  foodStatusInfo,
  getEventBadges,
  getEventDetailSections,
  getEvidenceDetails,
  getVisibleEvents,
  escapeIcsText,
  groupEventsByDate,
  groupPlannedEvents,
  persistPlannedIds,
  restorePlannedIds,
  searchEvents,
  sortEvents,
  shiftCalendarMonth,
  shiftCalendarWeek,
  summarizeIcsExclusions,
  togglePlannedId,
} from "../lib/events.ts";

const dataset = JSON.parse(readFileSync(new URL("../data/events.json", import.meta.url), "utf8"));
const exclusions = JSON.parse(readFileSync(new URL("../data/event_curation_exclusions.json", import.meta.url), "utf8"));
const events = dataset.events;

test("loads the curated records with stable IDs and an exclusion archive", () => {
  assert.equal(dataset.schema_version, "1.2");
  assert.equal(dataset.exclusions_file, "data/event_curation_exclusions.json");
  assert.equal(events.length, 8);
  assert.ok(events.every((event) => typeof event.id === "string" && event.id.length > 0));
  assert.equal(new Set(events.map((event) => event.id)).size, events.length);
  assert.ok(events.every((event) => Array.isArray(event.conditions)));
  assert.equal(exclusions.excluded_count, 43);
  assert.equal(exclusions.excluded_events.length, 43);
  assert.equal(events.length + exclusions.excluded_count, 51);
  assert.deepEqual(
    Object.fromEntries(["confirmed_free", "provided_cost_unknown", "food_unconfirmed", "not_provided"].map((status) => [status, events.filter((event) => event.food_status === status).length])),
    { confirmed_free: 3, provided_cost_unknown: 5, food_unconfirmed: 0, not_provided: 0 },
  );
});

test("eligibility is normalized without widening student-specific scope or losing evidence", () => {
  const research = events.find((event) => event.title === "Research in the Arts and Humanities");
  assert.equal(research.eligibility, "All UC San Diego students; Arts and Humanities emphasized");
  assert.ok(research.evidence.eligibility.includes("open to all students"));
  const distribution = events.find((event) => event.title === "Free Food Distribution");
  assert.equal(distribution.eligibility, "Students, staff, faculty, and San Diego community members");
  assert.ok(distribution.evidence.eligibility.includes("faculty ,"));
  assert.ok(events.filter((event) => event.eligibility === null).every((event) => event.eligibility !== "Everyone"));
});

test("food and drink search finds food records without contextual or placeholder matches", () => {
  const drinkTitles = searchEvents(events, "drink").map((event) => event.title);
  assert.ok(drinkTitles.some((title) => title.includes("World AIDS Day")));
  assert.ok(drinkTitles.some((title) => title.includes("Destress with CLS")));
  assert.ok(drinkTitles.some((title) => title.includes("Global Coffee Hour")));
  assert.ok(searchEvents(events, "food").some((event) => event.title === "Global Coffee Hour"));
  assert.ok(searchEvents(events, "pastry").some((event) => event.title === "Global Coffee Hour"));
  assert.ok(!searchEvents(events, "food").some((event) => event.title.startsWith("Welcome to UC San Diego")));
  assert.deepEqual(searchEvents(events, "zz-no-event-term"), []);

  const teamMeeting = { ...events[0], title: "Research team meeting", description: "The team will discuss the project.", food_description: null };
  assert.deepEqual(searchEvents([teamMeeting], "tea"), []);
  const placeholderOnly = {
    ...events[0], title: "Campus event", description: "Food details are not confirmed by the source.",
    food_description: null, location: null, address: null, date: null,
  };
  assert.deepEqual(searchEvents([placeholderOnly], "food"), []);
  assert.deepEqual(searchEvents([{ ...placeholderOnly, description: "Location TBA · Date to be confirmed" }], "location"), []);
});

test("ordinary title, date, and location searches remain available", () => {
  assert.ok(searchEvents(events, "2026-11-20").some((event) => event.title === "Free Food Distribution"));
  assert.ok(searchEvents(events, "Malk Hall").some((event) => event.title === "Free Food Distribution"));
  assert.ok(searchEvents(events, "Research in the Arts").length > 0);
});

test("date and confirmed-food sorting handle unknown dates and stable ties", () => {
  const unknownDate = { ...events[0], id: "fixture-unknown-date", date: null };
  const sortable = [...events, unknownDate];
  const byDate = sortEvents(sortable, "date");
  const knownDates = byDate.map((event) => event.date).filter(Boolean);
  assert.deepEqual(knownDates, [...knownDates].sort());
  assert.equal(byDate.at(-1).id, unknownDate.id);
  for (const date of new Set(sortable.map((event) => event.date).filter(Boolean))) {
    assert.deepEqual(
      byDate.filter((event) => event.date === date).map((event) => event.id),
      sortable.filter((event) => event.date === date).map((event) => event.id),
    );
  }

  const byFood = sortEvents(sortable, "food");
  const rank = { confirmed_free: 0, provided_cost_unknown: 1, food_unconfirmed: 2, not_provided: 3 };
  const ranks = byFood.map((event) => rank[event.food_status]);
  assert.deepEqual(ranks, [...ranks].sort());
  for (const status of Object.keys(rank)) {
    const dates = byFood.filter((event) => event.food_status === status).map((event) => event.date);
    const known = dates.filter(Boolean);
    assert.deepEqual(known, [...known].sort());
    assert.ok(dates.slice(known.length).every((date) => date === null));
  }
});

test("food-cost filter uses only food_status and provides all three choices", () => {
  assert.deepEqual(foodCostFilterOptions.map(({ label }) => label), ["All", "Confirmed free", "Not confirmed free"]);
  assert.equal(filterEventsByFoodCost(events, "all").length, 8);
  assert.equal(filterEventsByFoodCost(events, "confirmed_free").length, 3);
  assert.ok(filterEventsByFoodCost(events, "confirmed_free").every((event) => event.food_status === "confirmed_free"));
  assert.equal(filterEventsByFoodCost(events, "not_confirmed_free").length, 5);
  assert.ok(filterEventsByFoodCost(events, "not_confirmed_free").every((event) => event.food_status !== "confirmed_free"));
  const notProvided = { ...events[0], id: "fixture-not-provided", food_status: "not_provided" };
  assert.ok(filterEventsByFoodCost([...events, notProvided], "not_confirmed_free").includes(notProvided));
});

test("food filter composes with search, sorting, and both browsing modes", () => {
  const filtered = getVisibleEvents(events, "food", "food", "not_confirmed_free");
  assert.ok(filtered.length > 0);
  assert.ok(filtered.every((event) => event.food_status !== "confirmed_free"));
  assert.ok(filtered.some((event) => event.title === "Global Coffee Hour"));
  const ranks = filtered.map((event) => event.food_status);
  const rank = { confirmed_free: 0, provided_cost_unknown: 1, food_unconfirmed: 2, not_provided: 3 };
  assert.deepEqual(ranks, [...ranks].sort((a, b) => rank[a] - rank[b]));

  // All events uses this result directly; By date groups the same filtered result.
  const groups = groupEventsByDate(filtered);
  const byDateMode = [...groups.dated.flatMap((group) => group.events), ...groups.undated];
  assert.deepEqual(new Set(byDateMode.map((event) => event.id)), new Set(filtered.map((event) => event.id)));
  assert.ok(byDateMode.every((event) => event.food_status !== "confirmed_free"));
  assert.ok(filterDateGroups(groups, "2026-11-18").dated.flatMap((group) => group.events).every((event) => event.food_status !== "confirmed_free"));
});

test("eligibility and participation appear once before the general description", () => {
  const archiveRecord = exclusions.excluded_events.find((item) => item.record.title.startsWith("Beyond Sentences")).record;
  const sections = getEventDetailSections(archiveRecord);
  assert.deepEqual(sections.map((section) => section.kind), ["eligibility", "participation", "description"]);

  const dashboard = readFileSync(new URL("../app/event-dashboard.tsx", import.meta.url), "utf8");
  assert.equal((dashboard.match(/<span className="font-semibold">Eligibility:/g) ?? []).length, 1);
  assert.equal((dashboard.match(/\{section\.condition\.evidence\}/g) ?? []).length, 0);
  assert.equal((dashboard.match(/\{condition\.evidence\}/g) ?? []).length, 1);

  const eventWithoutEligibility = events.find((event) => event.title.includes("World AIDS Day"));
  assert.equal(eventWithoutEligibility.eligibility, null);
  assert.deepEqual(getEventDetailSections(eventWithoutEligibility).map((section) => section.kind), ["description"]);
});

test("date browsing groups confirmed dates and keeps unknown dates separate", () => {
  const unknownDate = { ...events[0], id: "fixture-unknown-date", date: null };
  const groups = groupEventsByDate(sortEvents([...events, unknownDate], "date"));
  const dates = groups.dated.map((group) => group.date);
  assert.deepEqual(dates, [...dates].sort());
  assert.ok(groups.dated.some((group) => group.date === "2026-11-20"));
  assert.deepEqual(groups.undated.map((event) => event.id), [unknownDate.id]);
  assert.deepEqual(filterDateGroups(groups, "2026-11-20").dated.map((group) => group.date), ["2026-11-20"]);
  assert.deepEqual(filterDateGroups(groups, "__undated__").undated.map((event) => event.id), [unknownDate.id]);
});

test("food status badges remain distinct and admission alone does not become free food", () => {
  assert.equal(foodStatusInfo.confirmed_free.label, "Confirmed free food");
  assert.equal(foodStatusInfo.provided_cost_unknown.label, "Food provided · cost unknown");
  assert.equal(foodStatusInfo.food_unconfirmed.label, "Food unconfirmed");
  const archivedAdmission = exclusions.excluded_events.find((item) => item.record.title.startsWith("Beyond Sentences")).record;
  assert.ok(getEventBadges(archivedAdmission).some((badge) => badge.label === "Admission ≠ free food"));
  assert.ok(!getEventBadges(archivedAdmission).some((badge) => badge.label === "Confirmed free food"));
});

test("food and event conditions remain distinct with exact evidence and source URLs", () => {
  const html = readFileSync(new URL("../data/calendar_ucsd_edu_student-life.html", import.meta.url), "utf8");
  const worldAids = events.find((event) => event.title.includes("World AIDS Day"));
  const gisExpo = events.find((event) => event.title === "GIS Mini Expo");
  assert.ok(worldAids.conditions.some((condition) => condition.type === "limited_quantity" && condition.scope === "food"));
  assert.ok(gisExpo.conditions.some((condition) => condition.type === "limited_quantity" && condition.scope === "food"));
  for (const event of events) {
    for (const condition of event.conditions) {
      assert.ok(html.includes(condition.evidence));
      assert.ok(condition.source_url.startsWith("https://"));
    }
  }
  assert.equal(worldAids.conditions[0].evidence, worldAids.evidence.provides_food);
  assert.ok(!getEvidenceDetails(worldAids).some(([field]) => field === "provides_food"));
  assert.equal(gisExpo.conditions[0].evidence, gisExpo.evidence.provides_food);
});

test("date, time, and location nulls retain TBA labels", () => {
  assert.equal(displayDate(null), "Date TBA");
  assert.equal(displayTime({ start_time: null, end_time: null }), "Time TBA");
  assert.equal(displayLocation(null), "Location TBA");
});

test("planner add/remove and localStorage behavior remain intact", () => {
  const chosen = [events[0].id, events[1].id];
  assert.deepEqual(togglePlannedId([events[0].id], events[1].id), chosen);
  assert.deepEqual(togglePlannedId(chosen, events[0].id), [events[1].id]);
  assert.deepEqual(restorePlannedIds(JSON.stringify([...chosen, "stale-id", 42]), events), chosen);
  assert.deepEqual(restorePlannedIds("not-json", events), []);
  let savedKey;
  let savedValue;
  persistPlannedIds({ setItem: (key, value) => { savedKey = key; savedValue = value; } }, chosen);
  assert.equal(savedKey, "freebite-planned-event-ids");
  assert.deepEqual(JSON.parse(savedValue), chosen);
  const planned = groupPlannedEvents(events.filter((event) => ["2026-11-20", "2026-12-01"].includes(event.date)));
  assert.deepEqual(planned.dated.map((group) => group.date), ["2026-11-20", "2026-12-01"]);
});

test("retained records preserve source URLs and field-specific evidence", () => {
  for (const record of events) {
    assert.ok(record.source_url.startsWith("https://"));
    assert.ok(record.event_url?.startsWith("https://"));
    assert.equal(typeof record.evidence, "object");
    assert.equal(typeof record.extraction_evidence, "object");
  }
});

test("monthly calendar grid positions dates correctly and month navigation crosses year boundaries", () => {
  const november = buildCalendarMonth(2026, 11);
  assert.equal(november.weeks.length, 6);
  assert.equal(november.weeks[0][0].date, "2026-10-26");
  assert.equal(november.weeks[0][6].date, "2026-11-01");
  assert.equal(november.weeks[5][0].date, "2026-11-30");
  assert.ok(november.weeks[0][0].inMonth === false);
  assert.deepEqual(shiftCalendarMonth(2026, 11, 1), { year: 2026, month: 12 });
  assert.deepEqual(shiftCalendarMonth(2027, 1, -1), { year: 2026, month: 12 });
});

test("calendar event mapping keeps multiple same-day events together and undated records outside the grid", () => {
  const noDate = { ...events[0], id: "fixture-undated", date: null };
  const mapped = eventsByCalendarDate([...events, noDate]);
  assert.equal(mapped.dated.get("2026-11-20").length, 2);
  assert.ok(mapped.dated.get("2026-11-20").every((event) => event.date === "2026-11-20"));
  assert.deepEqual(mapped.undated.map((event) => event.id), [noDate.id]);
  assert.ok(!mapped.dated.has("null"));
});

test("All Events and My Plan calendar scopes follow selected Planner IDs", () => {
  const selectedIds = [events[1].id, events[4].id];
  assert.equal(filterCalendarEvents(events, selectedIds, "all").length, events.length);
  assert.deepEqual(filterCalendarEvents(events, selectedIds, "planned").map((event) => event.id), selectedIds);
  const afterRemoval = selectedIds.filter((id) => id !== events[1].id);
  assert.deepEqual(filterCalendarEvents(events, afterRemoval, "planned").map((event) => event.id), [events[4].id]);
  const afterAdd = [...afterRemoval, events[2].id];
  assert.deepEqual(filterCalendarEvents(events, afterAdd, "planned").map((event) => event.id), [events[2].id, events[4].id]);
});

test("weekly calendar builds Monday-to-Sunday dates and navigates by whole weeks", () => {
  assert.deepEqual(buildCalendarWeek("2026-11-18"), [
    "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22",
  ]);
  assert.equal(shiftCalendarWeek("2026-11-18", -1), "2026-11-09");
  assert.equal(shiftCalendarWeek("2027-01-03", 1), "2027-01-04");
  assert.throws(() => buildCalendarWeek("2026-02-30"), /valid YYYY-MM-DD/);
});

test("weekly schedule positions dated timed events and handles overlaps", () => {
  const week = buildCalendarWeek("2026-11-18");
  const schedule = buildWeeklySchedule(events, week);
  const nov20 = schedule.byDate.get("2026-11-20");
  assert.equal(nov20.length, 2);
  assert.deepEqual(nov20.map(({ event }) => event.start_time), ["12:00", "13:00"]);
  assert.equal(nov20[0].top, 280);
  assert.equal(nov20[0].height, 140);
  assert.equal(nov20[1].top, 336);
  assert.ok(nov20.every(({ columns }) => columns === 2));
  assert.notEqual(nov20[0].column, nov20[1].column);
  assert.ok(!schedule.byDate.has("2026-12-01"));
});

test("weekly schedule leaves missing or uncertain times unpositioned and keeps undated events separate", () => {
  const week = buildCalendarWeek("2026-11-18");
  const noStart = { ...events[1], id: "fixture-no-start", date: "2026-11-18", start_time: null };
  const invalidTime = { ...events[1], id: "fixture-invalid-time", date: "2026-11-19", start_time: "8 AM" };
  const outsideHours = { ...events[1], id: "fixture-outside-hours", date: "2026-11-19", start_time: "23:00", end_time: "23:30" };
  const noDate = { ...events[1], id: "fixture-no-date", date: null };
  const schedule = buildWeeklySchedule([...events, noStart, invalidTime, outsideHours, noDate], week);
  assert.deepEqual(new Set(schedule.untimed.map((event) => event.id)), new Set([noStart.id, invalidTime.id]));
  assert.deepEqual(schedule.outsideHours.map((event) => event.id), [outsideHours.id]);
  assert.ok(![...schedule.byDate.values()].flat().some(({ event }) => [noStart, invalidTime, outsideHours, noDate].some((item) => item.id === event.id)));
});

test("ICS text escaping covers backslashes, commas, semicolons, and line breaks", () => {
  assert.equal(escapeIcsText("a\\b,c;d\r\ne\nf"), "a\\\\b\\,c\\;d\\ne\\nf");
});

test("ICS export includes selected confirmed events with stable UIDs and source fields", () => {
  const selected = [events.find((event) => event.title === "Global Coffee Hour")];
  const timestamp = new Date("2026-11-14T12:30:00.000Z");
  const first = buildIcsCalendar(selected, timestamp);
  const second = buildIcsCalendar(selected, timestamp);
  assert.equal(first.exported.length, 1);
  assert.equal(first.excluded.length, 0);
  assert.match(first.content, /BEGIN:VCALENDAR\r\nVERSION:2\.0\r\n/);
  assert.match(first.content, /UID:event-43c6054370d9f406@freebite\.local\r\n/);
  assert.match(first.content, /DTSTART:20261118T080000\r\nDTEND:20261118T093000\r\n/);
  assert.match(first.content, /SUMMARY:Global Coffee Hour\r\n/);
  assert.match(first.content, /DESCRIPTION:iCOMMUNITY:/);
  assert.match(first.content, /LOCATION:Triton Administrative Services Building/);
  assert.match(first.content, /URL:https:\/\/calendar\.ucsd\.edu\/student-life/);
  assert.equal(first.content, second.content);
  assert.ok(first.content.endsWith("END:VCALENDAR\r\n"));
  assert.ok(!/(?<!\r)\n/.test(first.content));
});

test("ICS export excludes unknown dates and incomplete times without making all-day entries", () => {
  const unknownDate = { ...events[0], id: "fixture-no-date", date: null };
  const unknownStart = { ...events[0], id: "fixture-no-start", start_time: null };
  const unknownEnd = { ...events[0], id: "fixture-no-end", end_time: null };
  const result = buildIcsCalendar([events[0], unknownDate, unknownStart, unknownEnd], new Date("2026-11-14T00:00:00Z"));
  assert.equal(result.exported.length, 1);
  assert.equal(result.excluded.length, 3);
  assert.match(result.excluded[0].reason, /confirmed date/);
  assert.ok(result.excluded.slice(1).every(({ reason }) => reason.includes("confirmed start and end times")));
  assert.equal(summarizeIcsExclusions(result.excluded), "1 no confirmed date; 2 confirmed start and end times are required");
  assert.ok(!result.content.includes("VALUE=DATE"));
  assert.equal((result.content.match(/BEGIN:VEVENT/g) ?? []).length, 1);

  const empty = buildIcsCalendar([], new Date("2026-11-14T00:00:00Z"));
  assert.equal(empty.exported.length, 0);
  assert.equal(empty.content, "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//FreeBite//Food Events//EN\r\nCALSCALE:GREGORIAN\r\nEND:VCALENDAR\r\n");
});

test("calendar UI exports Planner selections only and reports exclusions", () => {
  const dashboard = readFileSync(new URL("../app/event-dashboard.tsx", import.meta.url), "utf8");
  assert.match(dashboard, /buildIcsCalendar\(plannedEvents\)/);
  assert.match(dashboard, /anchor\.download = "freebite-events\.ics"/);
  assert.match(dashboard, /No calendar file was created/);
  assert.match(dashboard, /Exported \$\{result\.exported\.length\}; excluded/);
  assert.match(dashboard, /calendarEvents\.dated\.get\(day\.date\)/);
  assert.match(dashboard, /Date to be confirmed/);
  assert.match(dashboard, />All Events<\/button>/);
  assert.match(dashboard, />My Plan<\/button>/);
  assert.match(dashboard, />Week<\/button>/);
  assert.match(dashboard, /Previous week/);
  assert.match(dashboard, /Next week/);
  assert.match(dashboard, /filterCalendarEvents\(events, plannedIds, calendarScope\)/);
  assert.match(dashboard, /<WeeklySchedule weekDates=\{weekDates\} schedule=\{weeklySchedule\}/);
  assert.match(dashboard, /planned \? "border-2 border-\[#557F58\] bg-\[#DDEBDD\]/);
});
