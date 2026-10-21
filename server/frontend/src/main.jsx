import React, { useEffect, useState, useMemo, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowUpRight,
  ShieldCheck,
  KeyRound,
  LayoutDashboard,
  Users,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ArrowLeft,
  Search,
  RefreshCw,
  Clock3,
  Keyboard,
  Coffee,
  LockKeyhole,
  Monitor,
  Check,
  X,
  Building2,
  Info,
  CalendarDays,
} from "lucide-react";
import "./style.css";
import Admin from "./Structure.jsx";
import { ExportMenu, DepartmentTable } from "./Reports.jsx";
const number = new Intl.NumberFormat("ru-RU");
const dt = (s, opts = {}) =>
  s
    ? new Date(s).toLocaleString("ru-RU", {
        timeZone: "Europe/Moscow",
        ...opts,
      })
    : "—";
const time = (s) =>
  s >= 3600
    ? `${number.format(Math.floor(s / 3600))} ч ${Math.floor((s % 3600) / 60)} м`
    : s > 0 && s < 60
      ? "< 1 м"
      : `${Math.floor(s / 60)} м`;
const states = {
  active: "Активность",
  afk: "AFK",
  unknown: "Неизвестно",
};
const errors = {
  invalid_credentials: "Логин или пароль не подошли.",
  session_expired: "Сессия завершена. Войди снова.",
  directory_unavailable: "FreeIPA временно недоступна. Попробуй чуть позже.",
  directory_stale:
    "Нет свежей связи с FreeIPA. Доступ возобновится после синхронизации.",
  login_throttled: "Слишком много попыток. Попробуй через 15 минут.",
  department_changed:
    "Отдел уже изменился. Закрой окно и открой его снова, чтобы загрузить актуальный состав.",
  department_name_or_group_in_use:
    "Такое название или LDAP-группа уже используются другим отделом.",
  group_not_found:
    "LDAP-группа недоступна. Обнови список или выбери ручное управление.",
  binding_changed: "Привязка уже изменилась. Обнови страницу.",
  personal_account_required:
    "Подтверди, что эта локальная учётка принадлежит выбранному сотруднику.",
  access_denied: "Нет доступа к этому разделу.",
  invalid_membership_date: "Дата вступления должна быть между 01.01.2020 и сегодняшним днём.",
  membership_date_requires_member: "Дата вступления задана для сотрудника вне состава отдела. Обнови настройки.",
  membership_date_overlaps_history: "Дата пересекается с прежним периодом работы в этом отделе. Выбери дату после его окончания.",
  department_required: "Выбери доступный отдел.",
  employee_not_found:
    "Нет данных о сотруднике в этом отделе за выбранный период.",
  invalid_period: "Проверь начало и конец периода.",
  period_too_long: "Выбери до 366 дней за один отчёт.",
  invalid_csrf: "Обнови страницу и повтори действие.",
};
let csrf = "";
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch("/api/v1" + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(csrf ? { "X-CSRF-Token": csrf } : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new Error("Нет связи с сервером. Проверь подключение.");
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("Сервер временно недоступен. Попробуй ещё раз.");
  }
  if (!response.ok) {
    if (response.status === 401 && !path.includes("/auth/"))
      window.dispatchEvent(new Event("session-expired"));
    throw new Error(
      errors[data.detail] ||
        `Не удалось выполнить запрос (${response.status}).`,
    );
  }
  return data;
}
function Brand() {
  return (
    <div className="brand">
      <Activity /> Пульс<span>OFFICE ACTIVITY</span>
    </div>
  );
}
function Login({ onLogin }) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(e.currentTarget);
    try {
      await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          login: data.get("login"),
          password: data.get("password"),
        }),
      });
      await onLogin();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login">
      <section className="login-story">
        <Brand />
        <div>
          <p className="eyebrow">КОМАНДА В ФОКУСЕ</p>
          <h1>
            Рабочий день.
            <br />В понятных деталях.
          </h1>
          <p>
            Активность, перерывы и ввод —<br />
            по отделам, сотрудникам и дням.
          </p>
          <div className="art-bars" aria-hidden="true">
            {[40, 64, 48, 88, 70, 100, 82, 58, 93, 68, 80, 46].map((h, i) => (
              <i key={i} style={{ height: h + "%" }} />
            ))}
          </div>
        </div>
        <p className="secure">
          <ShieldCheck size={18} /> Внутренняя система компании
        </p>
      </section>
      <section className="login-form">
        <div>
          <span className="login-icon">
            <KeyRound />
          </span>
          <h2>С возвращением</h2>
          <p className="muted">
            Войди под своей корпоративной учётной записью.
          </p>
          <form onSubmit={submit}>
            <label>
              Логин
              <input
                name="login"
                autoComplete="username"
                placeholder="ivan.petrov"
                required
                maxLength={128}
              />
            </label>
            <label>
              Пароль
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                placeholder="Пароль корпоративной учётной записи"
                required
                maxLength={1024}
              />
            </label>
            {error && (
              <div className="alert" role="alert">
                {error}
              </div>
            )}
            <button disabled={busy} className="primary">
              {busy ? "Входим…" : "Войти"} <ArrowUpRight size={18} />
            </button>
          </form>
          <small>
            Доступ к статистике определяется твоими правами.
            <br />
            Текст и содержимое ввода не сохраняются.
          </small>
        </div>
      </section>
    </main>
  );
}
function Empty({ title = "Пока нет данных", children }) {
  return (
    <div className="empty">
      <CalendarDays size={30} />
      <h3>{title}</h3>
      <p>
        {children ||
          "Данные появятся, когда клиент отправит первые интервалы активности."}
      </p>
    </div>
  );
}
function Metrics({ data, individual }) {
  const t = data.totals,
    observed = t.active + t.afk + t.unknown;
  return (
    <div className="metrics">
      {[
        [
          "Активность",
          time(t.active),
          observed
            ? `${Math.round((t.active / observed) * 100)}% времени наблюдения`
            : "Нет интервалов за период",
          Activity,
          "active",
        ],
        ["AFK", time(t.afk), "Нет ввода или экран заблокирован", Coffee, "afk"],
        [
          "Нажатия клавиш",
          number.format(t.keys),
          "Без сохранения текста",
          Keyboard,
          "keys",
        ],
      ].map(([title, value, sub, Icon, key]) => (
        <article className={"metric " + key} key={key}>
          <div className="metric-top">
            {title}
            <span>
              <Icon size={19} />
            </span>
          </div>
          <strong>{value}</strong>
          <small>{sub}</small>
        </article>
      ))}
    </div>
  );
}
function Chart({ days, individual }) {
  const oneMonth =
    !days.length || days[0].day.slice(0, 7) === days.at(-1).day.slice(0, 7);
  const max =
    Math.ceil(
      Math.max(3600, ...days.map((d) => d.active + d.afk + d.unknown)) / 3600,
    ) * 3600;
  return (
    <section className="panel rhythm">
      <div className="panel-heading">
        <div>
          <h3>Активность по дням</h3>
          <p>
            {individual
              ? "Время наблюдения сотрудника за выбранный период"
              : "Время наблюдения всей команды по дням"}
          </p>
        </div>
        <div className="legend">
          {Object.entries(states).map(([k, v]) => (
            <span key={k}>
              <i className={k} />
              {v}
            </span>
          ))}
        </div>
      </div>
      <div className="chart-scroll">
        <div
          className="chart"
          style={{
            minWidth: Math.max(620, days.length * (oneMonth ? 20 : 39) + 70),
          }}
        >
          <div className="chart-axis">
            <span>{Math.ceil(max / 3600)} ч</span>
            <span>{number.format(max / 7200)} ч</span>
            <span>0</span>
          </div>
          <div className="chart-plot">
            <div className="grid-lines">
              <i />
              <i />
              <i />
            </div>
            {days.map((d) => {
              const day = oneMonth
                  ? Number(d.day.slice(8, 10))
                  : d.day.slice(8, 10) + "." + d.day.slice(5, 7),
                weekend = [0, 6].includes(
                  new Date(d.day + "T12:00:00").getDay(),
                );
              const content = (
                <>
                  <span className="bar-stack">
                    {["unknown", "afk", "active"].map((k) => (
                      <i
                        key={k}
                        className={k}
                        style={{ height: `${(d[k] / max) * 100}%` }}
                      />
                    ))}
                  </span>
                  <span className="day-label">{day}</span>
                </>
              );
              const title = `${d.day}: активность ${time(d.active)}, AFK ${time(d.afk)}, ${number.format(d.keys)} нажатий`;
              return (
                <div
                  key={d.day}
                  className={`chart-day ${weekend ? "weekend" : ""}`}
                  title={title}
                >
                  {content}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div className="chart-foot">
        <span>
          {individual
            ? "Время по сотруднику"
            : "Сумма времени сотрудников · чел.-часы"}
        </span>
        <span>Москва · UTC+3</span>
      </div>
    </section>
  );
}
function Avatar({ name, small = false }) {
  return (
    <span className={"avatar " + (small ? "small" : "")}>
      {name
        .split(/[ ._-]/)
        .filter(Boolean)
        .slice(0, 2)
        .map((x) => x[0])
        .join("")
        .toUpperCase()}
    </span>
  );
}
function MembershipBadge({ person }) {
  const membership = person?.department_membership;
  if (!membership) return null;
  return <small className={"membership-status " + (membership.current ? "current" : "former")}>
    {membership.current ? "Сейчас в отделе" : `Выбыл из отдела ${dt(membership.left_at, {day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"})} · Москва`}
  </small>;
}
function Employees({ people, onSelect, query, setQuery }) {
  const [sort, setSort] = useState("active");
  const filtered = useMemo(
    () =>
      people
        .filter((p) =>
          (p.display_name + " " + p.principal)
            .toLowerCase()
            .includes(query.toLowerCase()),
        )
        .sort((a, b) =>
          sort === "name"
            ? a.display_name.localeCompare(b.display_name, "ru")
            : b.totals[sort] - a.totals[sort],
        ),
    [people, query, sort],
  );
  return (
    <section className="panel employees">
      <div className="panel-heading">
        <div>
          <h3>
            Сотрудники <span className="count">{people.length}</span>
          </h3>
          <p>Выбери сотрудника для подробного отчёта</p>
        </div>
        <div className="table-tools">
          <label className="search">
            <Search size={17} />
            <input
              placeholder="Имя или логин"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Поиск сотрудника"
            />
          </label>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            aria-label="Сортировка"
          >
            <option value="active">По активности</option>
            <option value="keys">По нажатиям</option>
            <option value="afk">По AFK</option>
            <option value="name">По имени</option>
          </select>
        </div>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Сотрудник</th>
              <th>Активность</th>
              <th>AFK</th>
              <th>Нажатия</th>
              <th>Дни с данными</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {filtered.map((p) => (
              <tr key={p.id}>
                <td>
                  <button className="person" onClick={() => onSelect(p.id)}>
                    <Avatar name={p.display_name} />
                    <span>
                      <b>{p.display_name}</b>
                      <MembershipBadge person={p} />
                      <small>
                        {p.principal}
                        {!p.enabled || !p.present
                          ? " · учётная запись отключена"
                          : ""}
                      </small>
                    </span>
                  </button>
                </td>
                <td>
                  <b>{p.days.length ? time(p.totals.active) : "—"}</b>
                  <div className="tiny-track">
                    <i
                      style={{
                        width:
                          (p.totals.active /
                            (p.totals.active +
                              p.totals.afk +
                              p.totals.unknown) || 0) *
                            100 +
                          "%",
                      }}
                    />
                  </div>
                </td>
                <td>{p.days.length ? time(p.totals.afk) : "—"}</td>
                <td className="numeric">
                  {p.days.length ? number.format(p.totals.keys) : "—"}
                </td>
                <td>
                  <span className={p.days.length ? "day-badge" : "muted"}>
                    {p.days.length || "Нет данных"}
                  </span>
                </td>
                <td>
                  <button
                    className="icon-button"
                    onClick={() => onSelect(p.id)}
                    aria-label={"Открыть " + p.principal}
                  >
                    <ChevronRight size={18} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && (
          <Empty title="Никого не нашли">
            Попробуй другой запрос или выбери другой отдел.
          </Empty>
        )}
      </div>
    </section>
  );
}
function PeriodDetail({ data }) {
  const days = data.employees[0]?.days || [];
  return (
    <section className="panel day-detail">
      <div className="panel-heading">
        <div>
          <h3>Хронология за период</h3>
          <p>Активность и AFK в течение каждого дня</p>
        </div>
        <span className="tag">Москва</span>
      </div>
      {!days.length ? (
        <Empty>За выбранный период нет интервалов наблюдения.</Empty>
      ) : (
        <>
          <div className="day-devices">
            <Monitor size={16} />
            {data.devices
              ?.map(
                (d) =>
                  (d.hostname || d.label) +
                  (d.local_account ? " · локальная учётка → LDAP" : ""),
              )
              .join(", ") || "Компьютер не определён"}
          </div>
          <div className="period-timelines">
            {days.map((day) => (
              <div key={day.day} className="timeline-row">
                <div className="timeline-date">
                  <b>
                    {dt(day.day + "T12:00:00+03:00", {
                      day: "numeric",
                      month: "long",
                      year: "numeric",
                    })}
                  </b>
                  <span>
                    Активность {time(day.active)} · AFK {time(day.afk)}
                  </span>
                </div>
                <div className="timeline">
                  {day.segments.map((s, i) => {
                    const start = new Date(s.start),
                      end = new Date(s.end),
                      mid = new Date(day.day + "T00:00:00+03:00");
                    return (
                      <i
                        key={i}
                        className={s.state}
                        style={{
                          left: (start - mid) / 864000 + "%",
                          width: (end - start) / 864000 + "%",
                        }}
                        title={`${states[s.state]} · ${dt(s.start, { hour: "2-digit", minute: "2-digit", second: "2-digit" })} — ${dt(s.end, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`}
                      />
                    );
                  })}
                </div>
                <div className="timeline-hours">
                  {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
                    <span key={h}>{String(h).padStart(2, "0")}:00</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <small>
            Пустые участки — нет наблюдений. При работе на нескольких ПК время
            объединяется.
          </small>
        </>
      )}
    </section>
  );
}
const todayInMoscow = () =>
  new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Moscow" });
function monthPeriod(month) {
  const [year, m] = month.split("-").map(Number);
  return {
    start: month + "-01",
    end: month + "-" + new Date(Date.UTC(year, m, 0)).getUTCDate(),
  };
}
function DateRange({ period, onChange }) {
  const [draft, setDraft] = useState(period),
    [error, setError] = useState("");
  useEffect(() => {
    setDraft(period);
    setError("");
  }, [period]);
  function apply(next) {
    const length = (new Date(next.end) - new Date(next.start)) / 86400000 + 1;
    if (
      !next.start ||
      !next.end ||
      !Number.isFinite(length) ||
      length < 1 ||
      next.start < "2020-01-01" ||
      next.end > "2099-12-31"
    ) {
      setError("Укажи начало и конец периода по порядку.");
      return;
    }
    if (length > 366) {
      setError("Выбери до 366 дней за один отчёт.");
      return;
    }
    setError("");
    onChange(next);
  }
  function preset(value) {
    const today = todayInMoscow();
    if (value === "today") apply({ start: today, end: today });
    if (value === "week")
      apply({
        start: new Date(new Date(today + "T00:00:00Z").getTime() - 6 * 86400000)
          .toISOString()
          .slice(0, 10),
        end: today,
      });
    if (value === "month") apply(monthPeriod(today.slice(0, 7)));
  }
  return (
    <form
      className="date-range"
      onSubmit={(e) => {
        e.preventDefault();
        apply(draft);
      }}
    >
      <div className="date-range-fields">
        <CalendarDays size={18} />
        <label>
          С
          <input
            aria-label="Начало периода"
            type="date"
            min="2020-01-01"
            max="2099-12-31"
            required
            value={draft.start}
            onChange={(e) => setDraft({ ...draft, start: e.target.value })}
          />
        </label>
        <label>
          По
          <input
            aria-label="Конец периода"
            type="date"
            min="2020-01-01"
            max="2099-12-31"
            required
            value={draft.end}
            onChange={(e) => setDraft({ ...draft, end: e.target.value })}
          />
        </label>
        <button
          className="apply-period"
          type="submit"
          disabled={draft.start === period.start && draft.end === period.end}
        >
          Применить
        </button>
      </div>
      <div className="date-presets">
        <button type="button" onClick={() => preset("today")}>
          Сегодня
        </button>
        <button type="button" onClick={() => preset("week")}>
          7 дней
        </button>
        <button type="button" onClick={() => preset("month")}>
          Этот месяц
        </button>
        <small>До 366 дней · обе даты включены</small>
      </div>
      {error && (
        <div className="period-error" role="alert">
          {error}
        </div>
      )}
    </form>
  );
}
function Dashboard({ user, refreshUser, onLogout }) {
  const [view, setView] = useState("overview"),
    [department, setDepartment] = useState(""),
    [period, setPeriod] = useState(() =>
      monthPeriod(todayInMoscow().slice(0, 7)),
    ),
    [employee, setEmployee] = useState(""),
    [allHistory, setAllHistory] = useState(false),
    [query, setQuery] = useState(""),
    [reportResult, setData] = useState(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [revision, setRevision] = useState(0);
  const reportDepartment = employee && allHistory ? "" : department;
  // Never render a new screen with a response belonging to the previous query.
  const reportKey = JSON.stringify([period.start, period.end, reportDepartment,
    employee, view, revision, user.id, user.is_admin, user.departments.map(d => d.id)]);
  const data = reportResult?.key === reportKey ? reportResult.data : null;
  useEffect(() => setAllHistory(false), [employee, department]);
  const available = user.is_admin || user.departments.length > 0;
  useEffect(() => {
    if (department && !user.departments.some((g) => g.id === department)) {
      setDepartment("");
      setEmployee("");
    }
  }, [user]);
  useEffect(() => {
    if (view === "admin" || !available) return;
    let live = true;
    setLoading(true);
    setError("");
    setData(null);
    api(
      `/reports/${view === "departments" ? "departments" : "period"}?start_date=${period.start}&end_date=${period.end}${reportDepartment ? "&department=" + reportDepartment : ""}${employee ? "&employee=" + employee + "&details=true" : ""}`,
    )
      .then((d) => {
        if (live) {
          setData({key: reportKey, data: d});
        }
      })
      .catch((e) => live && setError(e.message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [reportKey, available, user]);
  useEffect(() => {
    const context = document.modelContext;
    if (!context?.registerTool) return;
    const life = new AbortController();
    Promise.resolve(
      context.registerTool(
        {
          name: "select_activity_month",
          description: "Select the month shown in the activity report.",
          inputSchema: {
            type: "object",
            properties: {
              month: {
                type: "string",
                pattern: "^20[2-9][0-9]-(0[1-9]|1[0-2])$",
              },
            },
            required: ["month"],
            additionalProperties: false,
          },
          annotations: { readOnlyHint: false },
          execute: async (input) => {
            if (
              !input ||
              Object.keys(input).length !== 1 ||
              !/^20[2-9][0-9]-(0[1-9]|1[0-2])$/.test(input.month)
            )
              throw new Error("Invalid month");
            setPeriod(monthPeriod(input.month));
            setView("overview");
            await new Promise(requestAnimationFrame);
            return { month: input.month, status: "selected" };
          },
        },
        { signal: life.signal },
      ),
    ).catch(() => {});
    return () => life.abort();
  }, []);
  function navigate(next) {
    setView(next);
    setEmployee("");
    setQuery("");
  }
  const person = employee && data?.employees[0];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Brand />
        <p className="nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</p>
        <nav>
          {[
            ["overview", "Обзор команды", LayoutDashboard],
            ["departments", "Отделы", Building2],
            ...(user.is_admin ? [["admin", "Настройки", Settings]] : []),
          ].map(([key, label, Icon]) => (
            <button
              key={key}
              className={view === key ? "selected" : ""}
              onClick={() => navigate(key)}
            >
              <Icon size={19} />
              {label}
              {view === key && <i />}
            </button>
          ))}
          <button
            className="mobile-logout"
            onClick={onLogout}
            aria-label="Выйти"
            title="Выйти"
          >
            <LogOut size={19} />
            Выйти
          </button>
        </nav>
        <div className="sidebar-user">
          <Avatar name={user.display_name} small />
          <div>
            <b>{user.principal}</b>
            <small>{user.is_admin ? "Администратор" : "Руководитель"}</small>
          </div>
          <button title="Выйти" aria-label="Выйти" onClick={onLogout}>
            <LogOut size={18} />
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            Рабочее пространство <ChevronRight size={14} />
            <b>
              {view === "admin"
                ? "Настройки"
                : employee
                  ? "Сотрудник"
                  : view === "departments"
                    ? "Отделы"
                    : "Обзор команды"}
            </b>
          </div>
          <span className="topbar-status">
            <i /> Локальная система
          </span>
        </header>
        <main className="content">
          <div className="page-heading">
            <div>
              {employee && (
                <button className="back" onClick={() => setEmployee("")}>
                  <ArrowLeft size={16} /> К команде
                </button>
              )}
              <p className="page-kicker">
                {view === "admin" ? "УПРАВЛЕНИЕ" : "АКТИВНОСТЬ КОМАНДЫ"}
              </p>
              <h1>
                {view === "admin"
                  ? "Настройки"
                  : person
                    ? person.display_name
                    : employee
                      ? "Сотрудник"
                      : view === "departments"
                        ? "Обзор отделов"
                        : "Обзор команды"}
              </h1>
              <p className="muted">
                {view === "admin"
                  ? "Отделы, руководители и подключённые компьютеры"
                  : person
                    ? `${person.principal} · Учётная запись LDAP`
                    : "Рабочее время и перерывы — в одном месте"}
              </p>
            </div>
            {view !== "admin" && (
              <div className="filters">
                <label className="department-select">
                  <Building2 size={17} />
                  <select
                    value={department}
                    onChange={(e) => {
                      setDepartment(e.target.value);
                      setEmployee("");
                      setQuery("");
                    }}
                    aria-label="Отдел"
                  >
                    {available && (
                      <option value="">
                        {user.is_admin
                          ? "Все сотрудники"
                          : "Все доступные отделы"}
                      </option>
                    )}
                    {user.departments.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.name}
                      </option>
                    ))}
                    {!available && (
                      <option value="">Нет доступных отделов</option>
                    )}
                  </select>
                </label>
                <DateRange period={period} onChange={setPeriod} />
                <button
                  className="refresh icon-button"
                  disabled={loading}
                  aria-label="Обновить статистику"
                  onClick={() => {
                    setRevision((x) => x + 1);
                    refreshUser();
                  }}
                >
                  <RefreshCw size={18} className={loading ? "spin" : ""} />
                </button>
                <ExportMenu
                  period={period}
                  department={reportDepartment}
                  employee={employee}
                  disabled={!available || loading || !!error || !data}
                />
              </div>
            )}
          </div>
          {view !== "admin" && available && (
            <section className="history-scope" aria-label="Область статистики">
              <div><b>{reportDepartment ? "Статистика за время в отделе" : "Вся доступная история"}</b>
                <MembershipBadge person={person} />
                {person?.department_membership?.current === false && <p>В выбранном периоде есть прежняя история. Новая активность после выхода в этот отдел не входит.</p>}
                <p>{reportDepartment ? "Учитывается только время от вступления до выхода из выбранного отдела, в пределах указанного периода." : "За выбранный период, с учётом твоих прав доступа."}</p>
              </div>
              {employee && department && <div className="history-toggle" role="group" aria-label="История сотрудника">
                <button className={!allHistory ? "primary" : "secondary"} aria-pressed={!allHistory} onClick={() => setAllHistory(false)}>В этом отделе</button>
                <button className={allHistory ? "primary" : "secondary"} aria-pressed={allHistory} onClick={() => setAllHistory(true)}>Вся доступная история</button>
              </div>}
            </section>
          )}
          {view === "admin" ? (
            <Admin
              api={api}
              dt={dt}
              states={{ ...states, locked: "AFK" }}
              onChanged={refreshUser}
            />
          ) : !available ? (
            <section className="panel">
              <Empty title="Доступ к отделу ещё не назначен">
                Попроси администратора назначить тебя руководителем в настройках
                дашборда.
              </Empty>
            </section>
          ) : error ? (
            <div className="alert" role="alert">
              {error}
              <button onClick={() => setRevision((x) => x + 1)}>
                Повторить
              </button>
            </div>
          ) : loading || !data ? (
            <div
              className="skeleton"
              role="status"
              aria-label="Загружаем статистику"
            >
              <div />
              <div />
              <div />
            </div>
          ) : (
            <>
              <Metrics data={data} individual={!!employee} />
              {view === "overview" || employee ? (
                <Chart days={data.days} individual={!!employee} />
              ) : null}
              {view === "departments" ? (
                <DepartmentTable
                  data={data}
                  time={time}
                  number={number}
                  onSelect={(id) => {
                    setDepartment(id);
                    setEmployee("");
                    setView("overview");
                  }}
                />
              ) : employee ? (
                person && (
                  <>
                    <PeriodDetail data={data} />
                    <section className="panel daily-table">
                      <div className="panel-heading">
                        <h3>По дням</h3>
                        <span className="muted">
                          Дней с наблюдениями: {person.days.length}
                        </span>
                      </div>
                      <div className="table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Дата</th>
                              <th>Активность</th>
                              <th>AFK</th>
                              <th>Нажатия</th>
                            </tr>
                          </thead>
                          <tbody>
                            {person.days.map((d) => (
                              <tr key={d.day}>
                                <td>
                                  {dt(d.day + "T12:00:00+03:00", {
                                    day: "numeric",
                                    month: "long",
                                    year: "numeric",
                                  })}
                                </td>
                                <td>{time(d.active)}</td>
                                <td>{time(d.afk)}</td>
                                <td>{number.format(d.keys)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {!person.days.length && <Empty />}
                      </div>
                    </section>
                  </>
                )
              ) : (
                <Employees
                  people={data.employees}
                  onSelect={setEmployee}
                  query={query}
                  setQuery={setQuery}
                />
              )}
              <div className="report-notes">
                <Info size={17} />
                <div>
                  <p>
                    AFK — нет ввода более 3 минут или экран заблокирован.
                    Нажатия — количество событий клавиатуры, а не символов
                    текста.
                  </p>
                  <p>
                    {reportDepartment
                      ? "История отдела учитывается по датам членства, указанным в настройках. "
                      : ""}
                    Время на нескольких ПК объединяется. Нажатия относятся к дню
                    окончания интервала; интервалы на границе доступа исключены
                    из счётчика.
                  </p>
                  {data.unassigned_intervals > 0 && (
                    <p>
                      {number.format(data.unassigned_intervals)} интервалов без
                      подтверждённого сотрудника не вошли в отчёт.
                    </p>
                  )}
                </div>
              </div>
              <footer>
                Сформировано{" "}
                {dt(data.generated_at, { hour: "2-digit", minute: "2-digit" })}
                <span>Пульс · Office Activity</span>
              </footer>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
function App() {
  const [user, setUser] = useState(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  async function load() {
    const u = await api("/auth/me");
    csrf = u.csrf_token;
    setUser(u);
    return u;
  }
  useEffect(() => {
    load()
      .catch((e) => {
        if (e.message !== errors.session_expired) setError(e.message);
      })
      .finally(() => setLoading(false));
    const expired = () => {
      csrf = "";
      setUser(null);
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
      csrf = "";
      setUser(null);
    } catch (e) {
      setError(e.message);
    }
  }
  if (loading)
    return (
      <div className="boot">
        <Activity />
        <p>Открываем рабочее пространство…</p>
      </div>
    );
  return (
    <>
      {error && (
        <div className="global-error" role="alert">
          {error}
          <button onClick={() => setError("")} aria-label="Закрыть уведомление">
            <X size={18} />
          </button>
        </div>
      )}
      {user ? (
        <Dashboard
          user={user}
          refreshUser={() => load().catch((e) => setError(e.message))}
          onLogout={logout}
        />
      ) : (
        <Login onLogin={load} />
      )}
    </>
  );
}
createRoot(document.getElementById("root")).render(<App />);
