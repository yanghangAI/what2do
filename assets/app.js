(function () {
  "use strict";

  // Cloudflare Worker that stores satisfied/unsatisfied vote counts.
  // Set to "" to disable the vote UI entirely.
  var PUFFER_VOTES_URL = "https://puffer-votes.hangyang.workers.dev";

  var TZ = "America/New_York";
  var DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  var DAY_LABELS = {
    mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun",
  };
  var DAY_FULL = {
    mon: "Monday", tue: "Tuesday", wed: "Wednesday",
    thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday",
  };

  function dataUrl() {
    var params = new URLSearchParams(location.search);
    if (params.get("fixture") === "1") return "tests/fixtures/hours.sample.json";
    return "data/hours.json";
  }

  function nowInTz() {
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: TZ, hour12: false,
      weekday: "short", hour: "2-digit", minute: "2-digit",
    }).formatToParts(new Date());
    var lookup = {};
    parts.forEach(function (p) { lookup[p.type] = p.value; });
    var weekdayMap = { Mon: "mon", Tue: "tue", Wed: "wed", Thu: "thu", Fri: "fri", Sat: "sat", Sun: "sun" };
    var hour = parseInt(lookup.hour, 10);
    if (hour === 24) hour = 0;
    var minute = parseInt(lookup.minute, 10);
    return {
      day: weekdayMap[lookup.weekday],
      minutes: hour * 60 + minute,
    };
  }

  function toMinutes(hhmm) {
    var bits = hhmm.split(":");
    return parseInt(bits[0], 10) * 60 + parseInt(bits[1], 10);
  }

  function formatTime(hhmm) {
    var bits = hhmm.split(":");
    var h = parseInt(bits[0], 10);
    var m = parseInt(bits[1], 10);
    var suffix = h >= 12 ? "PM" : "AM";
    var h12 = ((h + 11) % 12) + 1;
    return h12 + ":" + (m < 10 ? "0" + m : m) + " " + suffix;
  }

  function nextDay(d) {
    return DAYS[(DAYS.indexOf(d) + 1) % 7];
  }

  function intervalsForDate(facility, iso) {
    // Pull intervals out of an events-based schedule for a specific
    // calendar date. Returns [] when no events match.
    if (!facility.events) return null;
    var out = [];
    for (var i = 0; i < facility.events.length; i++) {
      var ev = facility.events[i];
      if (ev.date === iso) out.push({ open: ev.open, close: ev.close });
    }
    out.sort(function (a, b) { return toMinutes(a.open) - toMinutes(b.open); });
    return out;
  }

  function computeStatus(hours, now) {
    var today = hours[now.day] || [];
    for (var i = 0; i < today.length; i++) {
      var iv = today[i];
      if (now.minutes >= toMinutes(iv.open) && now.minutes < toMinutes(iv.close)) {
        return { open: true, until: iv.close };
      }
    }
    // Find next opening today
    for (var j = 0; j < today.length; j++) {
      var iv2 = today[j];
      if (toMinutes(iv2.open) > now.minutes) {
        return { open: false, nextDay: now.day, nextTime: iv2.open, isToday: true };
      }
    }
    // Walk forward up to 7 days
    var d = now.day;
    for (var k = 0; k < 7; k++) {
      d = nextDay(d);
      var slots = hours[d] || [];
      if (slots.length > 0) {
        return { open: false, nextDay: d, nextTime: slots[0].open, isToday: false };
      }
    }
    return { open: false, nextDay: null, nextTime: null, isToday: false };
  }

  function formatRelative(iso) {
    var then = new Date(iso).getTime();
    var diffMs = Date.now() - then;
    if (isNaN(diffMs)) return iso;
    var mins = Math.floor(diffMs / 60000);
    if (mins < 60) return mins + " min ago";
    var hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + " hr ago";
    var days = Math.floor(hrs / 24);
    return days + " day" + (days === 1 ? "" : "s") + " ago";
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "class") node.className = attrs[k];
        else if (k === "html") node.innerHTML = attrs[k];
        else node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) {
      if (c == null) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  // Facilities operated by UMass RecWell — affected by RecWell holiday
  // closures listed in the alert banner. Mullins (ice) and Puffer's
  // Pond are run by different orgs and aren't affected.
  var RECWELL_IDS = {
    "boyden-pool": 1, "curry-hicks-pool": 1, "recreation-center": 1,
    "rockwell-climbing": 1, "mullins-tennis": 1,
  };
  var TODAY_HOLIDAY = null; // {date, name} or null
  var HOLIDAYS_BY_DATE = {}; // iso → name, used to mark upcoming weekday rows

  function holidayForFacility(facility) {
    if (TODAY_HOLIDAY && RECWELL_IDS[facility.id]) return TODAY_HOLIDAY;
    var today = todayIsoInTz();
    var fc = (facility.closed_dates || []).filter(function (c) { return c.date === today; })[0];
    // Per-facility one-off closure — leave name null so renderStatus
    // shows a plain "CLOSED" badge (the underlying note explains why).
    if (fc) return { date: fc.date, name: null };
    return null;
  }

  function closureForFacilityOnDate(facility, iso) {
    // Returns a string label if the facility is closed on `iso`, else null.
    // Holidays carry their name (e.g. "Memorial Day"); per-facility
    // closures return an empty string so callers can render a plain
    // "Closed" with no redundant suffix.
    if (RECWELL_IDS[facility.id] && HOLIDAYS_BY_DATE[iso]) return HOLIDAYS_BY_DATE[iso];
    var fc = (facility.closed_dates || []).filter(function (c) { return c.date === iso; })[0];
    return fc ? "" : null;
  }

  function dateForUpcomingWeekday(weekdayIdx) {
    // weekdayIdx: 0=mon..6=sun (matches DAYS order). Returns the ISO
    // date of the next occurrence (today if it matches), in ET.
    var iso = todayIsoInTz();
    var parts = iso.split("-").map(Number);
    var dt = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    var todayIdx = (dt.getUTCDay() + 6) % 7; // shift Sun=0 → Mon=0
    var delta = (weekdayIdx - todayIdx + 7) % 7;
    dt.setUTCDate(dt.getUTCDate() + delta);
    return dt.toISOString().slice(0, 10);
  }

  function effectiveHours(facility) {
    // Blank out hours for the next-occurrence date of each weekday
    // when that date is closed (RecWell holiday OR facility-specific
    // dated closure scraped from notes).
    if (!RECWELL_IDS[facility.id] && !(facility.closed_dates || []).length) {
      return facility.hours;
    }
    var out = {};
    DAYS.forEach(function (d, i) {
      var occursOn = dateForUpcomingWeekday(i);
      out[d] = closureForFacilityOnDate(facility, occursOn)
        ? []
        : (facility.hours[d] || []);
    });
    return out;
  }

  function statusFromEvents(facility, now) {
    // Walk events sorted by (date, open). First event today and not
    // yet ended → open. Otherwise the next future event → "opens …".
    var todayIso = todayIsoInTz();
    var todayEvents = (intervalsForDate(facility, todayIso) || []);
    for (var i = 0; i < todayEvents.length; i++) {
      var iv = todayEvents[i];
      if (now.minutes >= toMinutes(iv.open) && now.minutes < toMinutes(iv.close)) {
        return { open: true, until: iv.close };
      }
    }
    var pending = (facility.events || []).filter(function (ev) {
      if (ev.date < todayIso) return false;
      if (ev.date === todayIso) return toMinutes(ev.open) > now.minutes;
      return true;
    }).sort(function (a, b) {
      if (a.date !== b.date) return a.date < b.date ? -1 : 1;
      return toMinutes(a.open) - toMinutes(b.open);
    });
    if (!pending.length) return { open: false, nextDate: null, nextTime: null };
    return { open: false, nextDate: pending[0].date, nextTime: pending[0].open };
  }

  function renderStatus(facility, now) {
    var holiday = holidayForFacility(facility);
    if (holiday) {
      var label = holiday.name ? "CLOSED — " + holiday.name : "CLOSED today";
      return el("p", { class: "status closed" }, [label]);
    }
    if (facility.events) {
      var es = statusFromEvents(facility, now);
      if (es.open) {
        return el("p", { class: "status open" }, ["OPEN until " + formatTime(es.until)]);
      }
      if (!es.nextDate) {
        return el("p", { class: "status closed" }, ["CLOSED — no upcoming sessions"]);
      }
      var todayIso2 = todayIsoInTz();
      var label;
      if (es.nextDate === todayIso2) label = "today";
      else {
        var dt2 = new Date(Date.UTC.apply(null, es.nextDate.split("-").map(Number).map(function (v, i) { return i === 1 ? v - 1 : v; })));
        var wkIdx = (dt2.getUTCDay() + 6) % 7;
        label = DAY_FULL[DAYS[wkIdx]];
      }
      return el("p", { class: "status closed" }, ["CLOSED — opens " + label + " at " + formatTime(es.nextTime)]);
    }
    var s = computeStatus(effectiveHours(facility), now);
    if (s.open) {
      return el("p", { class: "status open" }, ["OPEN until " + formatTime(s.until)]);
    }
    if (!s.nextDay) {
      return el("p", { class: "status closed" }, ["CLOSED"]);
    }
    var when = s.isToday ? "today" : DAY_FULL[s.nextDay];
    return el("p", { class: "status closed" }, ["CLOSED — opens " + when + " at " + formatTime(s.nextTime)]);
  }

  function renderWeekTable(facility, now) {
    var todayIso = todayIsoInTz();
    var parts = todayIso.split("-").map(Number);
    var rows = [];
    var SHORT_MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    for (var offset = 0; offset < 7; offset++) {
      var dt = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + offset));
      var weekdayIdx = (dt.getUTCDay() + 6) % 7; // shift Sun=0 → Mon=0
      var weekdayKey = DAYS[weekdayIdx];
      var iso = dt.toISOString().slice(0, 10);
      var closureLabel = closureForFacilityOnDate(facility, iso);
      // Prefer dated events if the facility uses them.
      var slots = facility.events
        ? (intervalsForDate(facility, iso) || [])
        : (facility.hours[weekdayKey] || []);

      var label;
      if (closureLabel != null) {
        label = closureLabel ? "Closed — " + closureLabel : "Closed";
      } else if (slots.length === 0) {
        label = "Closed";
      } else {
        label = slots.map(function (iv) { return formatTime(iv.open) + " – " + formatTime(iv.close); }).join(", ");
      }

      // Compact label so the row never wraps on a narrow phone column.
      // Include month only on day-1 of a new month within the window.
      var includeMonth = dt.getUTCDate() === 1 || offset === 0;
      var dayName;
      if (offset === 0) {
        dayName = "Today";
      } else if (includeMonth) {
        dayName = DAY_LABELS[weekdayKey] + " " + SHORT_MONTHS[dt.getUTCMonth()] + " " + dt.getUTCDate();
      } else {
        dayName = DAY_LABELS[weekdayKey] + " " + dt.getUTCDate();
      }

      var attrs = {};
      if (offset === 0) attrs.class = "today";
      if (closureLabel != null) attrs.class = (attrs.class || "") + " holiday";
      rows.push(el("tr", attrs, [
        el("th", {}, [dayName]),
        el("td", {}, [label]),
      ]));
    }
    return el("table", { class: "week" }, [el("tbody", {}, rows)]);
  }

  function filterPastDateNote(note, todayIso) {
    // If the note mentions specific dates, drop dates that have already passed.
    // If every mentioned date is past, drop the whole note.
    var dateRe = /\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})\b/gi;
    var dates = [];
    var m;
    while ((m = dateRe.exec(note)) !== null) {
      var month = MONTH_NAMES[m[1].toLowerCase()];
      var iso = m[3] + "-" + String(month + 1).padStart(2, "0") + "-" + String(parseInt(m[2], 10)).padStart(2, "0");
      dates.push({ raw: m[0], iso: iso, start: m.index, end: m.index + m[0].length });
    }
    if (dates.length === 0) return note;
    var future = dates.filter(function (d) { return d.iso >= todayIso; });
    if (future.length === 0) return null;  // drop entire note
    if (future.length === dates.length) return note;  // nothing to remove
    // Some past, some future: rebuild keeping only future date mentions.
    var futureSet = new Set(future.map(function (d) { return d.raw; }));
    var rebuilt = note.replace(dateRe, function (match) {
      return futureSet.has(match) ? match : "";
    });
    // Clean up doubled separators left by removed dates
    rebuilt = rebuilt
      .replace(/[,;]\s*[,;]/g, ",")
      .replace(/[,;]\s*$/g, "")
      .replace(/:\s*[,;]/g, ":")
      .replace(/\s+/g, " ")
      .trim();
    return rebuilt;
  }

  function renderWaterQuality(wq) {
    var todayIso = todayIsoInTz();
    var testIso = (wq.latest_report && wq.latest_report.date) || wq.last_updated;
    var offSeason = !testIso || daysBetween(testIso, todayIso) > 21;
    var cls, label;
    if (offSeason) {
      cls = "offseason"; label = "OFF-SEASON";
    } else if (wq.status === "allowed") {
      cls = "open"; label = "SWIMMING ALLOWED";
    } else if (wq.status === "closed") {
      cls = "closed"; label = "POSTED CLOSED";
    } else {
      cls = "closed"; label = "STATUS UNKNOWN";
    }
    var children = [el("p", { class: "status " + cls }, [label])];
    var readings = wq.latest_report && wq.latest_report.readings;
    if (wq.beaches) {
      // Same color scale for both columns so users can read magnitude
      // at a glance — matches the collapsed scale below the card.
      var bandFor = function (n) {
        if (n == null) return "none";
        if (n <= 30)   return "pristine";
        if (n <= 126)  return "ok";
        if (n <= 235)  return "warn";
        if (n <= 1000) return "bad";
        return "danger";
      };
      var cell = function (n) {
        if (n == null) return el("td", { class: "wq-cell wq-none" }, ["—"]);
        return el("td", { class: "wq-cell wq-" + bandFor(n) }, [String(n)]);
      };
      var hasNumbers = readings && (
        readings.north_sample != null || readings.south_sample != null ||
        readings.north_geomean != null || readings.south_geomean != null
      );
      if (hasNumbers) {
        var beachRow = function (k) {
          var name = k === "north" ? "North Beach" : "South Beach";
          return el("tr", {}, [
            el("th", { scope: "row" }, [name]),
            cell(readings[k + "_sample"]),
            cell(readings[k + "_geomean"]),
          ]);
        };
        children.push(el("table", { class: "wq-table" }, [
          el("caption", {}, ["Bacteria levels (E. coli)"]),
          el("thead", {}, [el("tr", {}, [
            el("th", {}, [""]),
            el("th", {}, ["latest"]),
            el("th", {}, ["5-wk mean"]),
          ])]),
          el("tbody", {}, [beachRow("north"), beachRow("south")]),
        ]));
        var pdfHref = (wq.latest_report && wq.latest_report.url) || wq.report_url;
        var noteChildren = ["⚠ Latest-sample value is read from a handwritten cell — it may be wrong. Confirm with the "];
        if (pdfHref) {
          noteChildren.push(el("a", { href: pdfHref, target: "_blank", rel: "noopener" }, ["PDF"]));
          noteChildren.push(".");
        } else {
          noteChildren.push("PDF.");
        }
        children.push(el("p", { class: "beaches-note" }, noteChildren));
      } else {
        // No numbers extracted — fall back to per-beach pass/fail verdict.
        var verdictLi = function (k) {
          var s = wq.beaches[k];
          var verdict = s === "ok" ? "meets standards"
                      : s === "closed" ? "exceeds standards"
                      : "no data";
          return el("li", {}, [
            el("span", { class: "beach-name" }, [
              k === "north" ? "North Beach" : "South Beach",
            ]),
            document.createTextNode("  " + verdict),
          ]);
        };
        children.push(el("ul", { class: "beaches" }, [
          verdictLi("north"), verdictLi("south"),
        ]));
      }
    }
    // Compact info line. PDF link is embedded in the caveat above; no
    // need to duplicate it here.
    var infoBits = [];
    if (testIso) infoBits.push(el("span", {}, [
      "Tested ", el("strong", {}, [formatDateHeading(testIso, weekdayOfIso(testIso))]),
    ]));
    var infoLine = el("p", { class: "wq-info" }, []);
    infoBits.forEach(function (node, i) {
      if (i > 0) infoLine.appendChild(document.createTextNode(" · "));
      infoLine.appendChild(node);
    });
    children.push(infoLine);
    children.push(renderMpnScale());
    children.push(renderVoteBlock());
    return children;
  }

  // ---- Satisfaction vote --------------------------------------------------

  var VOTE_KEY = "puffer-vote";
  var VOTE_COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000;

  function lastVote() {
    try {
      var raw = localStorage.getItem(VOTE_KEY);
      if (!raw) return null;
      // Back-compat: older builds stored just a numeric timestamp.
      if (/^\d+$/.test(raw)) return { ts: parseInt(raw, 10), kind: null };
      return JSON.parse(raw);
    } catch (_) { return null; }
  }

  function lastVoteAge() {
    var v = lastVote();
    return v ? Date.now() - v.ts : Infinity;
  }

  function recordVote(kind) {
    try {
      localStorage.setItem(VOTE_KEY, JSON.stringify({ ts: Date.now(), kind: kind }));
    } catch (_) {}
  }

  function renderVoteBlock() {
    var wrap = el("div", { class: "wq-vote" }, []);
    if (!PUFFER_VOTES_URL) { wrap.hidden = true; return wrap; }

    var btnYes = el("button", { type: "button", class: "vote-btn vote-yes", title: "Satisfied with water quality" }, ["👍"]);
    var btnNo  = el("button", { type: "button", class: "vote-btn vote-no",  title: "Not satisfied" }, ["👎"]);
    var tally = el("span", { class: "wq-vote-tally" }, ["…"]);
    var row = el("p", { class: "wq-vote-row" }, [
      el("span", { class: "wq-vote-label" }, ["Water OK today?"]),
      btnYes, btnNo, tally,
    ]);
    var status = el("p", { class: "wq-vote-status" }, []);
    var contact = el("p", { class: "wq-vote-contact", hidden: true }, [
      "Have a complaint? Email ",
      el("a", { href: "mailto:publichealth@amherstma.gov" }, ["publichealth@amherstma.gov"]),
      " or call ",
      el("a", { href: "tel:+14132593077" }, ["(413) 259-3077"]),
      " (Amherst Dept. of Public Health).",
    ]);
    wrap.appendChild(row);
    wrap.appendChild(status);
    wrap.appendChild(contact);

    function showCounts(data) {
      var s = data.satisfied || 0;
      var u = data.unsatisfied || 0;
      var total = s + u;
      if (total === 0) { tally.textContent = "no votes yet"; return; }
      var pct = Math.round((s / total) * 100);
      tally.textContent = "👍 " + s + "  👎 " + u + "  (" + pct + "% · " + total + ")";
    }

    function disableButtons(msg) {
      btnYes.disabled = true;
      btnNo.disabled = true;
      status.textContent = msg;
    }

    var prev = lastVote();
    var age = prev ? Date.now() - prev.ts : Infinity;
    if (age < VOTE_COOLDOWN_MS) {
      var daysLeft = Math.ceil((VOTE_COOLDOWN_MS - age) / 86400000);
      var dayStr = daysLeft === 1 ? "1 day" : daysLeft + " days";
      disableButtons("You already voted this week. You can vote again in " + dayStr + ".");
      if (prev && prev.kind === "unsatisfied") contact.hidden = false;
    }

    fetch(PUFFER_VOTES_URL, { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(showCounts)
      .catch(function () { tally.textContent = ""; });

    function vote(kind) {
      if (btnYes.disabled) return;
      btnYes.disabled = true;
      btnNo.disabled  = true;
      status.textContent = "Submitting…";
      fetch(PUFFER_VOTES_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vote: kind }),
      })
        .then(function (r) {
          if (!r.ok) throw new Error("vote failed");
          return r.json();
        })
        .then(function (data) {
          recordVote(kind);
          showCounts(data);
          status.textContent = "Thanks! Only one vote per week — you can vote again in 7 days.";
          if (kind === "unsatisfied") contact.hidden = false;
        })
        .catch(function () {
          btnYes.disabled = false;
          btnNo.disabled  = false;
          status.textContent = "Couldn’t submit your vote. Please try again in a moment.";
        });
    }

    btnYes.addEventListener("click", function () { vote("satisfied"); });
    btnNo.addEventListener( "click", function () { vote("unsatisfied"); });
    return wrap;
  }

  function renderMpnScale() {
    // MA freshwater E. coli swim standards translated into a human-readable scale.
    var rows = [
      { range: "0 – 30",     band: "ok",     label: "Pristine",        note: "background levels; very clean" },
      { range: "31 – 126",   band: "ok",     label: "Good",            note: "below the 5-week mean limit" },
      { range: "127 – 235",  band: "warn",   label: "Caution",         note: "above 5-week mean limit but single sample still legal" },
      { range: "236 – 1,000", band: "bad",   label: "Posted closed",   note: "exceeds single-sample limit (235 MPN/100 ml)" },
      { range: "> 1,000",    band: "bad",    label: "Heavily contaminated", note: "avoid contact" },
    ];
    var rowEls = rows.map(function (r) {
      return el("tr", { class: "mpn-row mpn-" + r.band }, [
        el("td", { class: "mpn-range" }, [r.range]),
        el("td", { class: "mpn-label" }, [r.label]),
        el("td", { class: "mpn-note" }, [r.note]),
      ]);
    });
    return el("details", { class: "wq-scale" }, [
      el("summary", {}, ["What do the numbers mean?"]),
      el("p", { class: "wq-scale-intro" }, [
        "E. coli is counted in colonies (MPN = most probable number) per 100 ml of water. " +
        "Massachusetts requires every freshwater swim beach to stay at or below ",
        el("strong", {}, ["235 MPN/100 ml"]),
        " on any single sample, and a 5-week mean at or below ",
        el("strong", {}, ["126 MPN/100 ml"]),
        ". Rough guide:",
      ]),
      el("table", { class: "mpn-table" }, [el("tbody", {}, rowEls)]),
      el("p", { class: "wq-scale-foot" }, [
        "Numbers tend to spike a day or two after heavy rain (runoff from upstream " +
        "septic systems, geese, livestock, etc.), then recover. A single ",
        el("em", {}, ["high"]), " sample doesn't necessarily mean the water is unsafe " +
        "the next day — that's what the 5-week mean is for.",
      ]),
    ]);
  }

  function daysBetween(isoA, isoB) {
    var a = Date.UTC.apply(null, isoA.split("-").map(Number).map(function (v, i) { return i === 1 ? v - 1 : v; }));
    var b = Date.UTC.apply(null, isoB.split("-").map(Number).map(function (v, i) { return i === 1 ? v - 1 : v; }));
    return Math.round((b - a) / 86400000);
  }

  function weekdayOfIso(iso) {
    var bits = iso.split("-").map(Number);
    var d = new Date(Date.UTC(bits[0], bits[1] - 1, bits[2]));
    return ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][d.getUTCDay()];
  }

  function renderCard(facility, now) {
    var children = [el("h3", {}, [facility.name])];
    if (facility.scrape_status !== "ok") {
      children.push(el("p", { class: "stale-banner" }, [
        "Data may be outdated — last refreshed " + formatRelative(facility.last_scraped),
      ]));
    }
    if (facility.water_quality) {
      renderWaterQuality(facility.water_quality).forEach(function (c) { children.push(c); });
    } else {
      children.push(renderStatus(facility, now));
      children.push(renderWeekTable(facility, now));
    }
    var todayIso = todayIsoInTz();
    var visibleNotes = (facility.notes || [])
      .map(function (n) { return filterPastDateNote(n, todayIso); })
      .filter(function (n) { return n; });
    if (visibleNotes.length) {
      var ul = el("ul", { class: "notes" }, visibleNotes.map(function (n) {
        return el("li", {}, [n]);
      }));
      children.push(ul);
    }
    var meta = el("p", { class: "meta" }, []);
    if (facility.location && facility.location.maps_url) {
      meta.appendChild(el("a", { href: facility.location.maps_url, target: "_blank", rel: "noopener" }, [
        facility.location.label || "Map",
      ]));
      meta.appendChild(document.createTextNode(" · "));
    }
    if (facility.source_url) {
      meta.appendChild(el("a", { href: facility.source_url, target: "_blank", rel: "noopener" }, ["Source"]));
    }
    children.push(meta);
    return el("article", { class: "card" }, children);
  }

  var PROGRAM_GROUP_LABELS = {
    climbing: "Climbing",
    fitness: "Group Fitness",
  };

  function todayIsoInTz() {
    var parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(new Date());
    var m = {};
    parts.forEach(function (p) { m[p.type] = p.value; });
    return m.year + "-" + m.month + "-" + m.day;
  }

  function formatDateHeading(iso, weekday) {
    var bits = iso.split("-");
    var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    var mo = months[parseInt(bits[1], 10) - 1];
    return weekday + ", " + mo + " " + parseInt(bits[2], 10) + " " + bits[0];
  }

  function renderSchedule(days, programIndex) {
    var root = document.getElementById("schedule");
    if (!root) return;
    root.innerHTML = "";
    if (!days || !days.length) {
      root.appendChild(el("p", { class: "section-note" }, ["No upcoming classes."]));
      return;
    }
    var today = todayIsoInTz();
    var orientationRe = /15\s*minute\s*climbing\s*orientation/i;
    days.forEach(function (day) {
      if (day.date < today) return;
      var visibleEvents = day.events.filter(function (e) {
        return !orientationRe.test(e.name);
      });
      if (!visibleEvents.length) return;
      var isToday = day.date === today;
      var headingText = formatDateHeading(day.date, day.weekday) + (isToday ? " — Today" : "");
      var heading = el("h3", isToday ? { class: "today" } : {}, [headingText]);
      var list = el("ul", { class: "schedule-list" }, visibleEvents.map(function (e) {
        var url = programIndex[e.name.toLowerCase()];
        var nameNode = url
          ? el("a", { href: url, target: "_blank", rel: "noopener" }, [e.name])
          : el("span", {}, [e.name]);
        return el("li", {}, [
          el("span", { class: "t" }, [formatTime(e.time)]),
          nameNode,
        ]);
      }));
      root.appendChild(el("div", { class: "schedule-day" }, [heading, list]));
    });
    if (!root.children.length) {
      root.appendChild(el("p", { class: "section-note" }, ["No upcoming classes."]));
    }
  }

  function renderPrograms(programs, upcomingNames) {
    var root = document.getElementById("programs");
    if (!root) return;
    root.innerHTML = "";
    if (!programs || !programs.length) {
      root.appendChild(el("p", { class: "section-note" }, ["No programs available."]));
      return;
    }
    var byCat = {};
    programs.forEach(function (p) {
      (byCat[p.category] = byCat[p.category] || []).push(p);
    });
    // Sort each category so programs WITH upcoming sessions come first
    Object.keys(byCat).sort().forEach(function (cat) {
      var label = PROGRAM_GROUP_LABELS[cat] || cat;
      var list = el("ul", { class: "programs-list" }, byCat[cat]
        .slice()
        .sort(function (a, b) {
          var ua = upcomingNames.has(a.name.toLowerCase()) ? 0 : 1;
          var ub = upcomingNames.has(b.name.toLowerCase()) ? 0 : 1;
          if (ua !== ub) return ua - ub;
          return a.name.localeCompare(b.name);
        })
        .map(function (p) {
          var hasUpcoming = upcomingNames.has(p.name.toLowerCase());
          var attrs = hasUpcoming ? {} : { class: "program-empty", title: "No upcoming sessions" };
          return el("li", attrs, [
            el("a", { href: p.url, target: "_blank", rel: "noopener" }, [p.name]),
          ]);
        }));
      root.appendChild(el("div", { class: "programs-group" }, [
        el("h3", {}, [label]),
        list,
      ]));
    });
  }

  function formatCountdown(minutesLeft) {
    if (minutesLeft <= 0) return "closing now";
    if (minutesLeft < 60) return minutesLeft + " min left";
    var h = Math.floor(minutesLeft / 60);
    var m = minutesLeft % 60;
    if (m === 0) return h + "h left";
    return h + "h " + m + "m left";
  }

  function renderOpenNow(facilities, now) {
    var root = document.getElementById("open-now");
    if (!root) return;
    root.innerHTML = "";
    var openItems = [];
    facilities.forEach(function (f) {
      if (holidayForFacility(f)) return; // closed for today's holiday
      var status = f.events
        ? statusFromEvents(f, now)
        : computeStatus(effectiveHours(f), now);
      if (!status.open) return;
      var minutesLeft = toMinutes(status.until) - now.minutes;
      openItems.push({ facility: f, until: status.until, minutesLeft: minutesLeft });
    });
    if (!openItems.length) {
      root.appendChild(el("p", { class: "open-now-empty" }, [
        "Nothing open right now. Check the sections below for upcoming hours.",
      ]));
      return;
    }
    openItems.sort(function (a, b) { return a.minutesLeft - b.minutesLeft; });
    var list = el("ul", { class: "open-now-list" }, openItems.map(function (it) {
      var urgent = it.minutesLeft <= 30;
      return el("li", urgent ? { class: "urgent" } : {}, [
        el("span", { class: "on-name" }, [it.facility.name]),
        el("span", { class: "on-until" }, ["until " + formatTime(it.until)]),
        el("span", { class: "on-countdown" }, [formatCountdown(it.minutesLeft)]),
      ]);
    }));
    root.appendChild(list);
  }

  var MONTH_NAMES = {
    january: 0, february: 1, march: 2, april: 3, may: 4, june: 5,
    july: 6, august: 7, september: 8, october: 9, november: 10, december: 11,
  };

  function _ampmToMinutes(h, m, ampm) {
    var hour = parseInt(h, 10);
    var minute = parseInt(m || 0, 10);
    if (ampm.toLowerCase() === "am") hour = (hour === 12) ? 0 : hour;
    else hour = (hour === 12) ? 12 : hour + 12;
    return hour * 60 + minute;
  }

  function _extractAlertIntervals(text) {
    // Find every "H[:MM] AM/PM - H[:MM] AM/PM" interval in the alert text.
    var re = /(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*[-–]\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)/gi;
    var intervals = [];
    var m;
    while ((m = re.exec(text)) !== null) {
      intervals.push({
        open: _ampmToMinutes(m[1], m[2], m[3]),
        close: _ampmToMinutes(m[4], m[5], m[6]),
      });
    }
    return intervals;
  }

  function _scrapedIntervalsMinutes(facilities) {
    var set = new Set();
    facilities.forEach(function (f) {
      Object.keys(f.hours).forEach(function (day) {
        f.hours[day].forEach(function (iv) {
          var o = toMinutes(iv.open), c = toMinutes(iv.close);
          set.add(o + "-" + c);
        });
      });
    });
    return set;
  }

  function alertIsExpired(text, todayIso, facilities) {
    // 1. Date-based: if every "begin/start on <date>" date has passed.
    var dateRe = /(?:begin|start|effective|starting)[^.]{0,80}?\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})/gi;
    var latest = null;
    var m;
    while ((m = dateRe.exec(text)) !== null) {
      var month = MONTH_NAMES[m[1].toLowerCase()];
      var day = parseInt(m[2], 10);
      var year = parseInt(m[3], 10);
      var iso = year + "-" + String(month + 1).padStart(2, "0") + "-" + String(day).padStart(2, "0");
      if (latest === null || iso > latest) latest = iso;
    }
    if (latest && todayIso > latest) return true;

    // 2. Content-based: if every time interval announced in the alert
    //    already appears in our scraped facility data, the upstream hours
    //    page has caught up and the alert is redundant.
    var alertIntervals = _extractAlertIntervals(text);
    if (alertIntervals.length === 0) return false;
    var scraped = _scrapedIntervalsMinutes(facilities || []);
    var matched = alertIntervals.filter(function (iv) {
      return scraped.has(iv.open + "-" + iv.close);
    });
    return matched.length === alertIntervals.length;
  }

  function alertOverlapsWithCards(facilities, alertState, todayIso) {
    // If every facility named in alert_state has either already moved to
    // its summer hours (today >= start) or is currently masked with the
    // gap-closure note on its card, then the alert isn't telling the
    // reader anything the cards don't already show.
    if (!alertState) return false;
    var ids = Object.keys(alertState);
    if (!ids.length) return false;
    for (var i = 0; i < ids.length; i++) {
      var entry = alertState[ids[i]] || {};
      var start = entry.start_date;
      if (!start) return false;
      if (todayIso >= start) continue;
      var f = (facilities || []).filter(function (x) { return x.id === ids[i]; })[0];
      if (!f) return false;
      var gapNote = (f.notes || []).some(function (n) {
        return /Closed for semester transition/.test(n);
      });
      if (!gapNote) return false;
    }
    return true;
  }

  function renderAlert(text, facilities, alertState) {
    var root = document.getElementById("alert-banner");
    if (!root) return;
    if (!text) { root.hidden = true; return; }
    var today = todayIsoInTz();
    if (alertIsExpired(text, today, facilities)
        || alertOverlapsWithCards(facilities, alertState, today)) {
      root.hidden = true;
      return;
    }
    root.hidden = false;
    root.innerHTML = "";
    var inner = el("div", { class: "alert-inner" }, []);
    var lines = text.split("\n");
    var heading = lines.shift();
    inner.appendChild(el("p", { class: "alert-heading" }, [heading]));

    // Pull a one-line summary out of the body — the first line that
    // mentions a "begin/start on <date>" or "closed" phrase, otherwise
    // just the first non-empty line.
    var bodyLines = lines.filter(function (l) { return l.trim().length; });
    var summary = "";
    var summaryRe = /(begin|start|closed|will\s+open).{0,120}/i;
    for (var i = 0; i < bodyLines.length; i++) {
      if (summaryRe.test(bodyLines[i])) { summary = bodyLines[i].trim(); break; }
    }
    if (!summary && bodyLines.length) summary = bodyLines[0].trim();

    var bodyText = lines.join("\n").trim();
    if (bodyText) {
      var details = el("details", { class: "alert-details" }, []);
      var summaryEl = el("summary", { class: "alert-summary" }, [
        el("span", { class: "alert-summary-text" }, [summary]),
        el("span", { class: "alert-toggle-label" }, ["Show details"]),
      ]);
      details.appendChild(summaryEl);
      details.appendChild(el("pre", { class: "alert-body" }, [bodyText]));
      inner.appendChild(details);
    }
    inner.appendChild(el("p", { class: "alert-source" }, [
      el("a", { href: "https://www.umass.edu/recwell/", target: "_blank", rel: "noopener" },
        ["Source: umass.edu/recwell"]),
    ]));
    root.appendChild(inner);
  }

  function render(doc) {
    var now = nowInTz();
    var todayIso = todayIsoInTz();
    TODAY_HOLIDAY = null;
    HOLIDAYS_BY_DATE = {};
    (doc.holidays || []).forEach(function (h) {
      HOLIDAYS_BY_DATE[h.date] = h.name;
      if (h.date === todayIso) TODAY_HOLIDAY = h;
    });
    document.getElementById("updated").textContent =
      "Last updated " + formatRelative(doc.last_updated);
    renderAlert(doc.alert, doc.facilities, doc.alert_state);
    renderOpenNow(doc.facilities, now);
    ["swim", "ice", "climbing", "fitness", "tennis"].forEach(function (cat) {
      var container = document.querySelector('[data-cards-for="' + cat + '"]');
      container.innerHTML = "";
      doc.facilities
        .filter(function (f) { return f.category === cat; })
        .forEach(function (f) { container.appendChild(renderCard(f, now)); });
    });
    var programIndex = {};
    (doc.programs || []).forEach(function (p) {
      programIndex[p.name.toLowerCase()] = p.url;
    });
    renderSchedule(doc.schedule || [], programIndex);
    var todayStr = todayIsoInTz();
    var upcomingNames = new Set();
    (doc.schedule || []).forEach(function (day) {
      if (day.date < todayStr) return;
      day.events.forEach(function (e) {
        upcomingNames.add(e.name.toLowerCase());
      });
    });
    renderPrograms(doc.programs || [], upcomingNames);
  }

  function showError(message) {
    document.getElementById("updated").textContent = message;
  }

  fetch(dataUrl(), { cache: "no-cache" })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(render)
    .catch(function (e) { showError("Failed to load hours: " + e.message); });
})();
