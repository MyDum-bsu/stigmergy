// Mission Control: the whole board at a glance — who works, who needs you, what
// finished, what sits idle — and every open space under it. A card goes where
// its click says it goes.

import { View, div } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { agents, panes, spaces, terminals, home, run, theme } from "herdr";

// Whom to look at first; cards and counters both follow this order.
const RANK = { blocked: 0, working: 1, done: 2, idle: 3 };
const COUNTERS = ["working", "blocked", "done", "idle"];

// A warm veil over the theme's own background: the panel reads warm and dark
// without leaving the palette the person picked.
const WARM = "#c08a4a0f";
// The theme's colors at partial opacity: glass over that veil, cards first.
// Colors come as #rrggbb, and some (border, hover, selected) already carry an
// alpha of their own, which this replaces.
const glass = (color, alpha) => (color.length === 9 ? `${color.slice(0, 7)}${alpha}` : `${color}${alpha}`);

const duration = (ms) => {
  const m = Math.floor(ms / 60000);
  if (m < 1) return "<1m";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
};

// An agent's own name, else the terminal's title, else what it runs.
const nameOf = (agent, words) => {
  const word = words.find((w) => w.address === agent.address);
  return word?.name || agent.title || agent.program?.name || agent.address;
};

// Where a space is, the way a person writes it.
const place = (folder) => {
  const at = home();
  if (!folder) return "\u2013";
  return at && folder.startsWith(at) ? `~${folder.slice(at.length)}` : folder;
};

export default class MissionControl extends View {
  init(_props, cx) {
    // When each agent's status was last seen to change: the duration a card
    // shows. Kept across restarts, as the agents mod keeps its own marks.
    this.since = JSON.parse(localStorage.getItem("since") ?? "{}");
    // Durations age while nothing else moves, so the panel redraws itself.
    cx.timer.every(30000, (cx) => cx.notify());
  }

  track(list, now) {
    let dirty = false;
    for (const a of list) {
      if (this.since[a.address]?.s === a.status) continue;
      this.since[a.address] = { s: a.status, at: now };
      dirty = true;
    }
    if (!dirty) return;
    // An agent gone for a week is not coming back under that address.
    const listed = new Set(list.map((a) => a.address));
    for (const [address, seen] of Object.entries(this.since)) {
      if (!listed.has(address) && now - seen.at > 7 * 86400000) delete this.since[address];
    }
    localStorage.setItem("since", JSON.stringify(this.since));
  }

  head(t, agentCount, spaceCount) {
    const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
    return h_flex()
      .px(16)
      .pt(15)
      .pb(10)
      .flex_none()
      .items_center()
      .justify_between()
      .child(
        v_flex()
          .gap(2)
          .child(div().text_size(15).font_semibold().text_color(t.foreground).child("Mission Control"))
          .child(div().text_size(11.5).text_color(t.dim).child(`${plural(agentCount, "agent")} \u00b7 ${plural(spaceCount, "space")}`)),
      );
  }

  // Four counters, one per status: lit when it has anything to say.
  counters(t, counts) {
    return h_flex()
      .px(12)
      .pb(2)
      .gap(6)
      .flex_none()
      .children(
        COUNTERS.map((status) => {
          const on = counts[status] > 0;
          const color = on ? t[status] : t.dim;
          return v_flex()
            .id(`mc-count-${status}`)
            .flex_1()
            .min_w(0)
            .gap(2)
            .p(8)
            .rounded(10)
            .bg(glass(color, on ? "1f" : "0a"))
            .border(1)
            .border_color(glass(color, on ? "3d" : "1a"))
            .child(
              h_flex()
                .gap(5)
                .items_center()
                .child(div().size(6).rounded(3).flex_none().bg(color))
                .child(div().text_size(15).font_semibold().text_color(color).child(String(counts[status]))),
            )
            .child(div().text_size(10).text_color(on ? t.muted : t.dim).child(status));
        }),
      );
  }

  section(t, title, note, color) {
    return h_flex()
      .px(4)
      .pt(12)
      .pb(6)
      .flex_none()
      .items_center()
      .gap(6)
      .child(div().text_size(10.5).font_semibold().text_color(t.dim).child(title))
      .child(div().flex_1())
      .when(Boolean(note), (el) => el.child(div().text_size(10.5).text_color(color ?? t.dim).child(note)));
  }

  empty(t, text) {
    return div()
      .mb(7)
      .p(12)
      .rounded(10)
      .bg(glass(t.raised, "80"))
      .border(1)
      .border_color(t.border)
      .text_size(11.5)
      .text_color(t.dim)
      .child(text);
  }

  chip(t, status) {
    const color = t[status] ?? t.dim;
    return h_flex()
      .flex_none()
      .gap(4)
      .items_center()
      .px(6)
      .h(16)
      .rounded(5)
      .bg(glass(color, "1f"))
      .child(div().size(5).rounded(3).flex_none().bg(color))
      .child(div().text_size(10).font_medium().text_color(color).child(status));
  }

  // Name, its space, its status and how long it has been in it. Blocked cards
  // are the ones that come to you; the rest wait their turn.
  agentCard(t, agent, words, now) {
    const color = t[agent.status] ?? t.dim;
    const hot = agent.status === "blocked";
    const seen = this.since[agent.address]?.at;
    return h_flex()
      .id(`mc-agent-${agent.address}`)
      .mb(7)
      .p(10)
      .gap(9)
      .rounded(10)
      .items_stretch()
      .bg(hot ? glass(t.blocked, "1a") : glass(t.raised, "e6"))
      .border(1)
      .border_color(hot ? glass(t.blocked, "47") : t.border)
      .cursor_pointer()
      .hover((el) => el.bg(hot ? glass(t.blocked, "26") : t.hover))
      .tooltip(`${agent.space_name || agent.space} \u00b7 click to focus`)
      .on_click(() => run("agent.focus", { terminal: agent.address }))
      .child(
        div()
          .w(3)
          .flex_none()
          .rounded(2)
          .bg(color)
          .when(agent.status === "working", (el) => el.loop("opacity", { from: 0.35, to: 1, period: 1400 })),
      )
      .child(
        v_flex()
          .flex_1()
          .min_w(0)
          .gap(4)
          .child(
            h_flex()
              .gap(8)
              .items_center()
              .child(
                div()
                  .flex_1()
                  .min_w(0)
                  .truncate()
                  .text_size(13)
                  .text_color(agent.status === "idle" ? t.muted : t.foreground)
                  .child(nameOf(agent, words)),
              )
              .child(div().flex_none().text_size(10.5).text_color(t.dim).child(seen ? duration(now - seen) : "")),
          )
          .child(
            h_flex()
              .gap(8)
              .items_center()
              .child(div().flex_1().min_w(0).truncate().text_size(11.5).text_color(t.dim).child(agent.space_name || agent.space))
              .child(this.chip(t, agent.status)),
          ),
      );
  }

  // Name, where it lives, how many terminals it holds.
  spaceCard(t, space, ps) {
    const tabs = new Set((space.tabs ?? []).map((tab) => tab.id));
    const count = ps.filter((p) => p.terminal && tabs.has(p.tab)).length;
    const color = (space.status && t[space.status]) || t.dim;
    const on = space.active;
    return h_flex()
      .id(`mc-space-${space.id}`)
      .mb(7)
      .p(10)
      .gap(9)
      .rounded(10)
      .items_center()
      .bg(on ? t.selected : glass(t.raised, "e6"))
      .border(1)
      .border_color(on ? glass(t.accent, "59") : t.border)
      .cursor_pointer()
      .hover((el) => el.bg(on ? t.selected : t.hover))
      .tooltip(place(space.folder))
      .on_click(() => run("space.select", { id: space.id }))
      .child(
        h_flex()
          .size(20)
          .flex_none()
          .rounded(6)
          .items_center()
          .justify_center()
          .bg(glass(color, space.status ? "26" : "12"))
          .child(div().text_size(10.5).font_bold().text_color(color).child([...(space.name || "?")][0].toUpperCase())),
      )
      .child(
        v_flex()
          .flex_1()
          .min_w(0)
          .gap(4)
          .child(
            h_flex()
              .gap(8)
              .items_center()
              .child(
                div()
                  .flex_1()
                  .min_w(0)
                  .truncate()
                  .text_size(13)
                  .text_color(on ? t.foreground : t.muted)
                  .child(space.name),
              )
              .when(Boolean(space.machine), (el) => el.child(div().flex_none().text_size(10).text_color(t.dim).child(space.machine))),
          )
          .child(
            h_flex()
              .gap(8)
              .items_center()
              .child(div().flex_1().min_w(0).truncate().text_size(11.5).text_color(t.dim).child(place(space.folder)))
              .child(
                div()
                  .flex_none()
                  .px(6)
                  .h(16)
                  .rounded(5)
                  .bg(glass(t.foreground, "12"))
                  .text_size(10)
                  .text_color(t.muted)
                  .child(`${count} terminal${count === 1 ? "" : "s"}`),
              ),
          ),
      );
  }

  render() {
    const t = theme();
    const now = Date.now();
    const all = agents();
    this.track(all, now);
    const list = [...all].sort((x, y) => RANK[x.status] - RANK[y.status]);
    const counts = { working: 0, blocked: 0, done: 0, idle: 0 };
    for (const a of list) counts[a.status] = (counts[a.status] ?? 0) + 1;
    const ps = panes();
    const sp = spaces();
    const words = terminals();
    return v_flex()
      .id("mc-root")
      .size_full()
      .min_h(0)
      .bg(t.canvas)
      .border_l(1)
      .border_color(t.border)
      .child(
        v_flex()
          .size_full()
          .min_h(0)
          .bg(WARM)
          .child(this.head(t, list.length, sp.length))
          .child(this.counters(t, counts))
          .child(
            v_flex()
              .id("mc-scroll")
              .flex_1()
              .min_h(0)
              .px(12)
              .pb(16)
              .overflow_y_scrollbar()
              .mode("always")
              .child(this.section(t, "Agents", counts.blocked ? `${counts.blocked} need you` : null, t.blocked))
              .when(list.length === 0, (el) => el.child(this.empty(t, "No agent reports a status yet.")))
              .children(list.map((agent) => this.agentCard(t, agent, words, now)))
              .child(this.section(t, "Spaces", null))
              .when(sp.length === 0, (el) => el.child(this.empty(t, "No spaces open.")))
              .children(sp.map((space) => this.spaceCard(t, space, ps))),
          ),
      );
  }
}
