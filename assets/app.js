(function () {
  "use strict";

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

  function renderStatus(facility, now) {
    var s = computeStatus(facility.hours, now);
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
    var tbody = el("tbody", {}, DAYS.map(function (d) {
      var slots = facility.hours[d] || [];
      var label = slots.length === 0
        ? "Closed"
        : slots.map(function (iv) { return formatTime(iv.open) + " – " + formatTime(iv.close); }).join(", ");
      return el("tr", d === now.day ? { class: "today" } : {}, [
        el("th", {}, [DAY_LABELS[d]]),
        el("td", {}, [label]),
      ]);
    }));
    return el("table", { class: "week" }, [tbody]);
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
      cls = "offseason"; label = "OFF-SEASON — no current testing";
    } else if (wq.status === "allowed") {
      cls = "open"; label = "SWIMMING ALLOWED";
    } else if (wq.status === "closed") {
      cls = "closed"; label = "POSTED CLOSED";
    } else {
      cls = "closed"; label = "STATUS UNKNOWN";
    }
    var children = [el("p", { class: "status " + cls }, [label])];
    // Prominent test-date line up top.
    if (testIso) {
      var dateLine = el("p", { class: "wq-testdate" }, [
        "Tested ", el("strong", {}, [formatDateHeading(testIso, weekdayOfIso(testIso))]),
      ]);
      if (wq.latest_report && wq.latest_report.url) {
        dateLine.appendChild(document.createTextNode(" · "));
        dateLine.appendChild(el("a", {
          href: wq.latest_report.url, target: "_blank", rel: "noopener",
        }, ["View report PDF"]));
      } else if (wq.report_url) {
        dateLine.appendChild(document.createTextNode(" · "));
        dateLine.appendChild(el("a", {
          href: wq.report_url, target: "_blank", rel: "noopener",
        }, ["All reports"]));
      }
      children.push(dateLine);
    }
    if (wq.beaches) {
      var beachLabel = function (k) {
        var s = wq.beaches[k];
        var verdict = s === "ok" ? "meets standards"
                    : s === "closed" ? "exceeds standards"
                    : "no data";
        return el("span", { class: "beach beach-" + s }, [
          k === "north" ? "North Beach: " : "South Beach: ", verdict,
        ]);
      };
      children.push(el("p", { class: "beaches" }, [
        beachLabel("north"),
        document.createTextNode(" · "),
        beachLabel("south"),
      ]));
    }
    if (wq.detail) {
      children.push(el("p", { class: "wq-detail" }, [wq.detail]));
    }
    children.push(el("p", { class: "wq-standard" }, [
      "Standard: ≤235 MPN/100 ml E. coli (single sample); ≤126 MPN/100 ml (geomean). " +
      "Click the report PDF for the actual MPN values — the form is a scanned, hand-filled sheet so we can't reliably extract numbers.",
    ]));
    return children;
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
      var status = computeStatus(f.hours, now);
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

  function renderAlert(text, facilities) {
    var root = document.getElementById("alert-banner");
    if (!root) return;
    if (!text) { root.hidden = true; return; }
    if (alertIsExpired(text, todayIsoInTz(), facilities)) {
      root.hidden = true;
      return;
    }
    root.hidden = false;
    root.innerHTML = "";
    var inner = el("div", { class: "alert-inner" }, []);
    var lines = text.split("\n");
    var heading = lines.shift();
    inner.appendChild(el("p", { class: "alert-heading" }, [heading]));
    var bodyText = lines.join("\n").trim();
    if (bodyText) {
      var pre = el("pre", { class: "alert-body" }, [bodyText]);
      inner.appendChild(pre);
    }
    inner.appendChild(el("p", { class: "alert-source" }, [
      el("a", { href: "https://www.umass.edu/recwell/", target: "_blank", rel: "noopener" },
        ["Source: umass.edu/recwell"]),
    ]));
    root.appendChild(inner);
  }

  function render(doc) {
    var now = nowInTz();
    document.getElementById("updated").textContent =
      "Last updated " + formatRelative(doc.last_updated);
    renderAlert(doc.alert, doc.facilities);
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
