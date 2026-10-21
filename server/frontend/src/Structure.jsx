import React, { useState, useEffect, useRef } from "react";
import {
  Building2,
  Plus,
  Link2,
  Unlink,
  Monitor,
  X,
  Check,
  RefreshCw,
  Search,
} from "lucide-react";
function Picker({ people, value, onChange, title, disabled = false, membershipDates, onDateChange }) {
  const [query, setQuery] = useState("");
  const filtered = people.filter((p) =>
    (p.display_name + " " + p.principal)
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <section className="people-picker">
      <div className="picker-heading">
        <h3>{title}</h3>
        <span className="count">{value.length}</span>
      </div>
      <label className="search">
        <Search size={16} />
        <input
          value={query}
          placeholder="Имя или логин"
          aria-label={"Поиск: " + title}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <div className="head-options">
        {filtered.map((p) => (
          <div key={p.id} className="membership-row"><label className="check-row">
            <input
              type="checkbox"
              disabled={
                disabled ||
                ((!p.enabled || !p.present) && !value.includes(p.id))
              }
              checked={value.includes(p.id)}
              onChange={(e) =>
                onChange(
                  e.target.checked
                    ? [...value, p.id]
                    : value.filter((id) => id !== p.id),
                )
              }
            />
            <span>
              {p.display_name}
              <small>
                {p.principal}
                {!p.enabled || !p.present ? " · отключён" : ""}
              </small>
            </span>
          </label>
          {onDateChange && value.includes(p.id) && <label className="membership-date">В отделе с
            <input type="date" aria-label={"В отделе с: " + p.principal} min="2020-01-01"
              max={new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())}
              value={membershipDates?.[p.id] || ""} onChange={e => onDateChange(p.id,e.target.value)} />
            {!membershipDates?.[p.id] && <small>С момента сохранения</small>}
          </label>}
          </div>
        ))}
        {!filtered.length && (
          <p className="muted picker-empty">Сотрудники не найдены</p>
        )}
      </div>
    </section>
  );
}
function LocalAccount({ account, people, api, onSaved }) {
  const [employee, setEmployee] = useState(account.employee_id || ""),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function save() {
    setBusy(true);
    setError("");
    try {
      await api("/admin/local-accounts", {
        method: "PUT",
        body: JSON.stringify({
          device_id: account.device_id,
          local_user: account.local_user,
          local_uid: account.local_uid,
          employee_id: employee || null,
          previous_binding_id: account.binding_id,
          personal_account_confirmed: confirmed,
        }),
      });
      await onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="local-account">
      <div>
        <b>{account.hostname || account.label}</b>
        <small>
          Локальная учётка: {account.local_user} · UID {account.local_uid}
        </small>
      </div>
      <label>
        Сотрудник из LDAP
        <select
          value={employee}
          onChange={(e) => {
            setEmployee(e.target.value);
            setConfirmed(false);
          }}
        >
          <option value="">Не привязан</option>
          {people
            .filter(
              (p) => (p.enabled && p.present) || p.id === account.employee_id,
            )
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name} · {p.principal}
              </option>
            ))}
        </select>
      </label>
      {employee && employee !== account.employee_id && (
        <label className="check-row">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>Это личная локальная учётка выбранного сотрудника</span>
        </label>
      )}
      <button
        className="secondary"
        disabled={
          busy ||
          employee === (account.employee_id || "") ||
          (!!employee && !confirmed)
        }
        onClick={save}
      >
        {busy
          ? "Сохраняем…"
          : employee
            ? "Связать с сотрудником"
            : "Отвязать сотрудника"}
      </button>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
export default function Admin({ api, dt, states, onChanged }) {
  const [data, setData] = useState(null),
    [accounts, setAccounts] = useState([]),
    [edit, setEdit] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [saved, setSaved] = useState("");
  const modalRef = useRef(null);
  async function load() {
    const [d, a] = await Promise.all([
      api("/admin/settings"),
      api("/admin/local-accounts"),
    ]);
    setData(d);
    setAccounts(a.accounts);
  }
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!edit) return;
    const previous = document.activeElement,
      modal = modalRef.current;
    modal.querySelector("input:not(:disabled),button:not(:disabled)")?.focus();
    function key(e) {
      if (e.key === "Escape" && !busy) {
        e.preventDefault();
        setEdit(null);
      }
      if (e.key === "Tab") {
        const list = [
            ...modal.querySelectorAll(
              "button:not(:disabled),input:not(:disabled),select:not(:disabled)",
            ),
          ],
          first = list[0],
          last = list.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, [edit?.id, busy, !!edit]);
  function open(d) {
    setError("");
    setSaved("");
    setEdit(
      d
        ? { ...d, dateChanges: {} }
        : {
            id: null,
            name: "",
            ldap_group_id: null,
            members: [],
            heads: [],
            enabled: true,
            revision: null,
            membership_starts: {}, dateChanges: {},
          },
    );
  }
  function chooseGroup(id) {
    const group = data.groups.find((g) => g.id === id);
    if (group)
      setEdit({
        ...edit,
        ldap_group_id: group.id,
        name: group.name,
        members: group.members,
      });
  }
  async function save() {
    setBusy(true);
    setError("");
    try {
      await api("/admin/departments" + (edit.id ? "/" + edit.id : ""), {
        method: edit.id ? "PUT" : "POST",
        body: JSON.stringify({
          name: edit.name,
          ldap_group_id: edit.ldap_group_id,
          enabled: edit.enabled,
          members: edit.members,
          heads: edit.heads,
          revision: edit.revision,
          membership_starts: Object.fromEntries(Object.entries(edit.dateChanges).filter(([id,day]) => edit.members.includes(id) && day)),
        }),
      });
      setEdit(null);
      setSaved("Отдел сохранён");
      await load();
      await onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const choices =
    data?.groups.filter(
      (g) =>
        g.present &&
        !data.departments.some(
          (d) => d.id !== edit?.id && d.ldap_group_id === g.id,
        ),
    ) || [];
  return (
    <>
      {error && !edit && (
        <div className="alert" role="alert">
          {error}
          <button
            onClick={() =>
              load()
                .then(() => setError(""))
                .catch((e) => setError(e.message))
            }
          >
            Повторить
          </button>
        </div>
      )}
      {saved && (
        <div className="success" role="status">
          <Check size={18} />
          {saved}
        </div>
      )}
      {!data ? (
        <div className="loading">Загружаем настройки…</div>
      ) : (
        <>
          <div className="admin-intro">
            <span className="login-icon">
              <Building2 />
            </span>
            <div>
              <h3>Отделы под твоим управлением</h3>
              <p>
                Подключи группу LDAP для автоматического состава или создай
                ручной отдел. Можно переключить режим в любой момент, сохранив
                историю.
              </p>
            </div>
          </div>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h3>Отделы и доступ</h3>
                <p>
                  LDAP обновлён{" "}
                  {dt(data.directory?.last_success, {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}{" "}
                  · каждые 5 минут
                </p>
              </div>
              <button className="primary compact" onClick={() => open(null)}>
                <Plus size={17} />
                Создать отдел
              </button>
            </div>
            {!data.departments.length ? (
              <div className="empty">
                <Building2 size={28} />
                <h3>Создай первый отдел</h3>
                <p>
                  Сотрудники уже доступны из LDAP. Осталось выбрать, как
                  объединить их в отделы.
                </p>
              </div>
            ) : (
              <div className="group-list">
                {data.departments.map((d) => (
                  <div className="group-row" key={d.id}>
                    <span
                      className={"group-icon " + (d.enabled ? "enabled" : "")}
                    >
                      <Building2 size={20} />
                    </span>
                    <div className="group-info">
                      <b>{d.name}</b>
                      <small>
                        Участников: {d.members.length} · Руководителей:{" "}
                        {d.heads.length}
                        {!d.enabled ? " · скрыт" : ""}
                      </small>
                      <small>
                        {d.ldap_group_id
                          ? d.source_available
                            ? `LDAP · ${d.ldap_name}`
                            : "LDAP-группа недоступна · сохранён последний состав"
                          : "Ручной отдел"}
                      </small>
                    </div>
                    <span
                      className={"tag " + (d.ldap_group_id ? "blue" : "green")}
                    >
                      {d.ldap_group_id ? (
                        <>
                          <Link2 size={13} /> LDAP
                        </>
                      ) : (
                        <>
                          <Unlink size={13} /> Вручную
                        </>
                      )}
                    </span>
                    <button className="secondary" onClick={() => open(d)}>
                      Настроить
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
          <section className="panel devices">
            <div className="panel-heading">
              <div>
                <h3>Компьютеры</h3>
                <p>Состояние доставки данных</p>
              </div>
              <Monitor size={22} />
            </div>
            {data.devices.map((d) => (
              <div className="device-row" key={d.id}>
                <Monitor size={22} />
                <div>
                  <b>{d.label}</b>
                  <small>
                    {d.hostname || "Имя ещё не получено"} · клиент{" "}
                    {d.agent_version || "—"}
                  </small>
                  <small className="device-person">
                    Последний интервал:
                    {d.principal
                      ? `${d.display_name} · ${d.principal}`
                      : "Учётная запись не подтверждена"}
                    {d.state ? ` · ${states[d.state] || d.state}` : ""}
                    {d.resolution === "local_ldap_binding"
                      ? " · локальная учётка → LDAP"
                      : ""}
                  </small>
                </div>
                <span
                  className={
                    "tag " +
                    (d.enabled && Date.now() - new Date(d.last_seen) < 120000
                      ? "green"
                      : "")
                  }
                >
                  {!d.enabled
                    ? "Отключён"
                    : d.last_seen && Date.now() - new Date(d.last_seen) < 120000
                      ? "На связи"
                      : "Нет свежих данных"}
                </span>
                <small>Последний пакет: {dt(d.last_seen)}</small>
              </div>
            ))}
          </section>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h3>ПК вне домена</h3>
                <p>Локальная учётка компьютера → сотрудник из LDAP</p>
              </div>
              <Monitor size={21} />
            </div>
            <div className="account-note">
              После установки клиента здесь появятся локальные учётки. Привязка
              действует только для выбранного компьютера и новых интервалов.
              История до привязки не меняется. Для общей учётки с разными людьми
              нужен выбор сотрудника на клиенте.
            </div>
            {accounts.length ? (
              accounts.map((a) => (
                <LocalAccount
                  key={
                    a.device_id +
                    ":" +
                    a.local_user +
                    ":" +
                    a.local_uid +
                    ":" +
                    a.binding_id
                  }
                  account={a}
                  people={data.employees}
                  api={api}
                  onSaved={load}
                />
              ))
            ) : (
              <div className="empty">
                <Monitor size={26} />
                <h3>Локальных учёток пока нет</h3>
                <p>
                  Они появятся после первого пакета от клиента на ПК вне домена.
                </p>
              </div>
            )}
          </section>
        </>
      )}
      {edit && (
        <div
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget && !busy) setEdit(null);
          }}
        >
          <section
            className="modal structure-modal"
            ref={modalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="edit-title"
          >
            <div className="modal-heading">
              <div>
                <small>ОТДЕЛ И СОСТАВ</small>
                <h2 id="edit-title">
                  {edit.id ? "Настроить отдел" : "Новый отдел"}
                </h2>
              </div>
              <button
                className="icon-button"
                disabled={busy}
                onClick={() => setEdit(null)}
                aria-label="Закрыть"
              >
                <X />
              </button>
            </div>
            <fieldset className="mode-switch">
              <legend>Управление отделом</legend>
              <label>
                <input
                  type="radio"
                  name="source"
                  checked={!edit.ldap_group_id}
                  onChange={() => setEdit({ ...edit, ldap_group_id: null })}
                />
                <Unlink size={16} />
                Вручную
              </label>
              <label>
                <input
                  type="radio"
                  name="source"
                  disabled={!choices.length && !edit.ldap_group_id}
                  checked={!!edit.ldap_group_id}
                  onChange={() => chooseGroup(choices[0]?.id)}
                />
                <Link2 size={16} />
                Из LDAP-группы
              </label>
            </fieldset>
            {edit.ldap_group_id ? (
              <>
                <label>
                  Группа LDAP
                  <select
                    value={edit.ldap_group_id}
                    onChange={(e) => chooseGroup(e.target.value)}
                  >
                    {!choices.some((g) => g.id === edit.ldap_group_id) && (
                      <option value={edit.ldap_group_id}>
                        Группа недоступна
                      </option>
                    )}
                    {choices.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.name} · {g.members.length} участников
                      </option>
                    ))}
                  </select>
                </label>
                <p className="mode-note">
                  Имя и состав берутся из LDAP. После сохранения состав будет
                  соответствовать выбранной группе. Чтобы менять его здесь,
                  выбери «Вручную».
                </p>
              </>
            ) : (
              <>
                <label>
                  Название отдела
                  <input
                    value={edit.name}
                    maxLength={120}
                    placeholder="Например, Отдел продаж"
                    onChange={(e) => setEdit({ ...edit, name: e.target.value })}
                  />
                </label>
                <p className="mode-note">
                  Изменения LDAP не затрагивают ручной отдел. После отключения
                  синхронизации сохраняются имя, участники и история.
                </p>
              </>
            )}
            <Picker
              title="Сотрудники отдела"
              people={data.employees}
              value={edit.members}
              onChange={(members) => setEdit({ ...edit, members })}
              disabled={!!edit.ldap_group_id}
              membershipDates={{...edit.membership_starts, ...edit.dateChanges}}
              onDateChange={(id, day) => {
                const dateChanges = {...edit.dateChanges};
                if (day) dateChanges[id] = day; else delete dateChanges[id];
                setEdit({...edit, dateChanges});
              }}
            />
            <Picker
              title="Руководители с доступом"
              people={data.employees}
              value={edit.heads}
              onChange={(heads) => setEdit({ ...edit, heads })}
            />
            <label className="check-row">
              <input
                type="checkbox"
                checked={edit.enabled}
                onChange={(e) =>
                  setEdit({ ...edit, enabled: e.target.checked })
                }
              />
              <span>
                Отдел доступен в отчётах
                <small>
                  Отключение скрывает отдел и доступ руководителей, сохраняя
                  историю.
                </small>
              </span>
            </label>
            <p className="mode-note">
              По умолчанию новые сотрудники учитываются с момента сохранения.
              Можно указать фактическую дату вступления (с начала дня, Москва).
              Изменение даты пересчитает историю отдела и доступ руководителей.
              Для LDAP-отдела даты тоже можно менять: синхронизация сохраняет их,
              пока сотрудник остаётся в группе. Удаление из отдела действует сейчас.
            </p>
            {error && (
              <div className="alert" role="alert">
                {error}
              </div>
            )}
            <div className="modal-actions">
              <button
                className="secondary"
                disabled={busy}
                onClick={() => setEdit(null)}
              >
                Отмена
              </button>
              <button
                className="primary"
                disabled={busy || !edit.name.trim()}
                onClick={save}
              >
                {busy ? "Сохраняем…" : "Сохранить"}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
