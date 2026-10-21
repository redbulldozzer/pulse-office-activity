import React, { useState } from "react";
import { Download, Building2, ChevronRight } from "lucide-react";
export function DepartmentTable({ data, onSelect, time, number }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h3>Статистика отделов</h3>
          <p>Общий итог выше учитывает каждого сотрудника один раз</p>
        </div>
        <Building2 size={21} />
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Отдел</th>
              <th>Сотрудники</th>
              <th>Активность</th>
              <th>AFK</th>
              <th>Нажатия</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.departments?.map((d) => (
              <tr key={d.id}>
                <td>
                  <button
                    className="text-button"
                    onClick={() => onSelect(d.id)}
                  >
                    {d.name}
                  </button>
                  <small className="block">
                    {d.ldap_group_id ? "LDAP" : "Ручной отдел"}
                  </small>
                </td>
                <td>
                  {d.observed_count} с данными / {d.employees_count}
                </td>
                <td>{time(d.totals.active)}</td>
                <td>{time(d.totals.afk)}</td>
                <td>{number.format(d.totals.keys)}</td>
                <td>
                  <button
                    className="icon-button"
                    onClick={() => onSelect(d.id)}
                    aria-label={"Открыть отдел " + d.name}
                  >
                    <ChevronRight size={18} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data.departments?.length && (
          <div className="empty">
            <Building2 size={27} />
            <h3>Отделы пока не настроены</h3>
            <p>
              Администратор может создать их вручную или подключить группы LDAP.
            </p>
          </div>
        )}
      </div>
      <p className="table-note">
        Каждый отдел учитывает только время членства в нём. Сотрудник может входить в несколько отделов. Поэтому сумма строк отделов
        может отличаться от общего итога. Общий отчёт администратора также
        включает сотрудников без отдела.
      </p>
    </section>
  );
}
export function ExportMenu({ period, department, employee, disabled }) {
  const [format, setFormat] = useState("xlsx");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function download(kind) {
    if (!kind) return;
    setBusy(true);
    setError("");
    try {
      const q = new URLSearchParams({
        start_date: period.start,
        end_date: period.end,
        kind,
        format,
      });
      if (department) q.set("department", department);
      if (employee && kind !== "departments") q.set("employee", employee);
      const response = await fetch("/api/v1/reports/export?" + q);
      if (!response.ok) {
        if (response.status === 401)
          window.dispatchEvent(new Event("session-expired"));
        throw new Error(
          response.status === 403
            ? "Доступ к выгрузке закрыт. Обнови страницу."
            : "Не удалось выгрузить отчёт. Обнови страницу и попробуй снова.",
        );
      }
      const blob = await response.blob(),
        url = URL.createObjectURL(blob),
        link = document.createElement("a");
      link.href = url;
      link.download = `activity-${kind}-${period.start}_${period.end}.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="export-control">
      <select
        aria-label="Формат выгрузки"
        value={format}
        disabled={busy}
        onChange={(e) => setFormat(e.target.value)}
      >
        <option value="xlsx">Excel (.xlsx)</option>
        <option value="csv">CSV</option>
      </select>
      <label className="export-select">
        <Download size={17} />
        <select
          aria-label="Выгрузить отчёт"
          value=""
          disabled={disabled || busy}
          onChange={(e) => download(e.target.value)}
        >
          <option value="" disabled>
            {busy ? "Выгружаем…" : "Выгрузить"}
          </option>
          <option value="employees">Сотрудники за период</option>
          <option value="daily">Сотрудники по дням</option>
          {!employee && <option value="departments">Сводка по отделам</option>}
        </select>
      </label>
      {error && (
        <div className="export-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
