
"use client";

import { useState } from "react";

type Event = {
  id: number;
  title: string;
  date: string;
  time: string;
  location: string;
  food: string;
  status: "free" | "unknown" | "unconfirmed";
};

const events: Event[] = [
  {
    id: 1,
    title: "Free Food Distribution",
    date: "2026-11-20",
    time: "12:00 PM – 2:30 PM",
    location: "Basic Needs Center",
    food: "Shelf-stable food & seasonal produce",
    status: "free",
  },
  {
    id: 2,
    title: "World AIDS Day",
    date: "2026-12-01",
    time: "Time to be confirmed",
    location: "UC San Diego",
    food: "Free boba drinks",
    status: "free",
  },
  {
    id: 3,
    title: "Destress with CLS",
    date: "",
    time: "Time to be confirmed",
    location: "UC San Diego",
    food: "Hot chocolate & pan dulce",
    status: "unknown",
  },
  {
    id: 4,
    title: "Campus Art Exhibition",
    date: "2026-11-21",
    time: "Time to be confirmed",
    location: "UC San Diego",
    food: "Food not confirmed",
    status: "unconfirmed",
  },
];

const statusInfo = {
  free: {
    label: "Free food confirmed",
    style: "bg-emerald-50 text-emerald-700",
  },
  unknown: {
    label: "Food price unknown",
    style: "bg-amber-50 text-amber-700",
  },
  unconfirmed: {
    label: "Food not confirmed",
    style: "bg-gray-100 text-gray-600",
  },
};


const searchAliases: Record<string, string[]> = {
  drink: ["drink", "drinks", "beverage", "beverages", "boba", "hot chocolate", "tea", "coffee", "juice", "latte"],
  drinks: ["drink", "drinks", "beverage", "beverages", "boba", "hot chocolate", "tea", "coffee", "juice", "latte"],
  beverage: ["drink", "drinks", "beverage", "beverages", "boba", "hot chocolate", "tea", "coffee", "juice", "latte"],
  snack: ["snack", "snacks", "pan dulce", "pastry", "cookies", "chips"],
  food: ["food", "meal", "lunch", "dinner", "snack", "produce"],
  sweet: ["sweet", "dessert", "pastry", "boba", "cookies", "chocolate"],
};


const week = [
  { day: "MON", date: "2026-11-16" },
  { day: "TUE", date: "2026-11-17" },
  { day: "WED", date: "2026-11-18" },
  { day: "THU", date: "2026-11-19" },
  { day: "FRI", date: "2026-11-20" },
  { day: "SAT", date: "2026-11-21" },
  { day: "SUN", date: "2026-11-22" },
];

function formatDate(date: string) {
  if (!date) return "Date TBD";

  return new Date(date + "T12:00:00").toLocaleDateString(
    "en-US",
    { month: "short", day: "numeric" }
  );
}

export default function Home() {
  const [selectedDate, setSelectedDate] = useState("2026-11-20");
  const [plannedIds, setPlannedIds] = useState<number[]>([1]);
  const [search, setSearch] = useState("");

  const plannedEvents = events.filter((event) =>
    plannedIds.includes(event.id)
  );


  const availableEvents = events.filter((event) => {
    const query = search.trim().toLowerCase();
  
    if (!query) return true;
  
    const searchableText = [
      event.title,
      event.food,
      event.location,
      event.time,
    ].join(" ").toLowerCase();
  
    const alternatives = searchAliases[query] ?? [query];
  
    return alternatives.some((term) =>
      searchableText.includes(term)
    );
  });
  

  function togglePlan(id: number) {
    setPlannedIds((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id]
    );
  }

  const selectedEvents = plannedEvents.filter(
    (event) => event.date === selectedDate
  );

  const otherDatedEvents = plannedEvents.filter(
    (event) => event.date && event.date !== selectedDate
  );
  
  const unscheduledEvents = plannedEvents.filter(
    (event) => !event.date
  );

  return (
    <main className="min-h-screen bg-[#F8F9F6] text-[#243B30]">
      {/* Navigation */}
      <nav className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6">
        <a href="#" className="text-2xl font-bold tracking-tight">
          freebite<span className="text-[#D68B60]">.</span>
        </a>

        <div className="flex items-center gap-6 text-sm font-medium">
          <a href="#" className="text-[#89938A] hover:text-[#243B30]">
            Discover
          </a>
          <a href="#" className="text-[#243B30]">
            Planner
          </a>
        </div>
      </nav>

      <div className="mx-auto max-w-7xl px-6 pb-20">
        {/* Heading */}
        <header className="mb-10 mt-8">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#89958B]">
            Your weekly food plan
          </p>

          <h1 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">
            Plan less. Eat better.
          </h1>

          <p className="mt-3 text-sm text-[#849087]">
            Find and organize free food opportunities around UC San Diego.
          </p>
        </header>

        {/* Week selector */}
        <section className="mb-10">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-semibold">Your week</h2>
            <span className="text-xs text-[#89938A]">
              November 16 – 22, 2026
            </span>
          </div>

          <div className="grid grid-cols-7 gap-2">
            {week.map((item) => {
              const active = selectedDate === item.date;
              const dayNumber = item.date.slice(-2);

              return (
                <button
                  key={item.date}
                  onClick={() => setSelectedDate(item.date)}
                  className={`rounded-xl border py-4 transition ${
                    active
                      ? "border-[#254A38] bg-[#254A38] text-white"
                      : "border-[#E7EAE3] bg-white hover:border-[#9BA99C]"
                  }`}
                >
                  <span className={`block text-xs ${
                    active ? "text-[#C8D9CB]" : "text-[#929D94]"
                  }`}>
                    {item.day}
                  </span>

                  <span className="mt-2 block text-lg font-semibold">
                    {dayNumber}
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        {/* Main dashboard */}
        <div className="grid items-start gap-8 lg:grid-cols-[1fr_320px]">

          {/* Available events */}
          <section>
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">
                  Food opportunities
                </h2>
                <p className="mt-1 text-sm text-[#89938A]">
                  Find something worth adding to your plan.
                </p>
              </div>

              <span className="text-xs text-[#89938A]">
                {availableEvents.length} events
              </span>
            </div>

            <div className="mb-5">
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search events, food, or locations..."
                className="w-full rounded-xl border border-[#E5E9E2] bg-white px-4 py-3 text-sm outline-none transition focus:border-[#567B60]"
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              {availableEvents.map((event) => {
                const isPlanned = plannedIds.includes(event.id);
                const status = statusInfo[event.status];

                return (
                  <article
                    key={event.id}
                    className="rounded-2xl border border-[#E7EAE3] bg-white p-5 transition hover:border-[#C5D0C5] hover:shadow-sm"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`rounded-full px-3 py-1 text-[11px] font-semibold ${status.style}`}>
                        {status.label}
                      </span>

                      <span className="text-xs text-[#89938A]">
                        {formatDate(event.date)}
                      </span>
                    </div>

                    <h3 className="mt-5 text-lg font-semibold">
                      {event.title}
                    </h3>

                    <p className="mt-2 min-h-10 text-sm leading-5 text-[#849087]">
                      {event.food}
                    </p>

                    <div className="mt-4 space-y-2 text-xs text-[#89938A]">
                      <p>◷ {event.time}</p>
                      <p>⌖ {event.location}</p>
                    </div>

                    <button
                      onClick={() => togglePlan(event.id)}
                      className={`mt-6 w-full rounded-lg py-2.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
                        isPlanned
                          ? "border border-[#DCE5DC] bg-[#F3F6F1] text-[#365B42]"
                          : "bg-[#254A38] text-white hover:bg-[#193B2B]"
                      }`}
                    >
                      {isPlanned ? "✓ Added to plan" : "+ Add to plan"}
                    </button>
                  </article>
                );
              })}
            </div>
          </section>

          {/* Planner sidebar */}
          <aside className="rounded-2xl border border-[#E7EAE3] bg-white p-5 lg:sticky lg:top-6">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">My plan</h2>
              <span className="rounded-full bg-[#EDF3EC] px-2.5 py-1 text-xs font-semibold text-[#42674A]">
                {plannedEvents.length} saved
              </span>
            </div>

            <p className="mt-2 text-sm text-[#89938A]">
              {formatDate(selectedDate)} · Selected day
            </p>

            <div className="mt-5 space-y-3">
              {selectedEvents.length > 0 ? (
                selectedEvents.map((event) => (
                  <div
                    key={event.id}
                    className="rounded-xl bg-[#F6F8F4] p-4"
                  >
                    <span className="text-xs font-medium text-[#66806A]">
                      {event.time}
                    </span>

                    <h3 className="mt-2 text-sm font-semibold">
                      {event.title}
                    </h3>

                    <p className="mt-1 text-xs text-[#89938A]">
                      {event.location}
                    </p>

                    <button
                      onClick={() => togglePlan(event.id)}
                      className="mt-3 text-xs font-medium text-[#A46A51] hover:underline"
                    >
                      Remove
                    </button>
                  </div>
                ))
              ) : (
                <div className="rounded-xl border border-dashed border-[#DCE3D9] px-4 py-8 text-center">
                  <p className="text-sm font-medium">Nothing planned yet</p>
                  <p className="mt-2 text-xs leading-5 text-[#929D94]">
                    Add a food event to organize your day.
                  </p>
                </div>
              )}
            </div>
            
            {/* Events planned for other dates */}
            {otherDatedEvents.length > 0 && (
              <div className="mt-6">
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#89938A]">
                  Other dates
                </h3>

                {otherDatedEvents.map((event) => (
                  <div key={event.id} className="mb-3 rounded-xl bg-[#F6F8F4] p-4">
                    <p className="text-xs text-[#66806A]">
                      {formatDate(event.date)}
                    </p>
                    <p className="mt-2 text-sm font-semibold">{event.title}</p>
                    <button
                      onClick={() => togglePlan(event.id)}
                      className="mt-3 text-xs text-[#A46A51]"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Events without confirmed dates */}
            {unscheduledEvents.length > 0 && (
              <div className="mt-6">
                <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#89938A]">
                  Date to be confirmed
                </h3>

                {unscheduledEvents.map((event) => (
                  <div key={event.id} className="mb-3 rounded-xl bg-[#F6F8F4] p-4">
                    <p className="text-sm font-semibold">{event.title}</p>
                    <p className="mt-1 text-xs text-[#89938A]">
                      {event.location}
                    </p>
                    <button
                      onClick={() => togglePlan(event.id)}
                      className="mt-3 text-xs text-[#A46A51]"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-6 border-t border-[#EEF0EB] pt-4">
              <p className="text-xs leading-5 text-[#929D94]">
                Events without confirmed dates will appear separately until their dates are announced.
              </p>
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
