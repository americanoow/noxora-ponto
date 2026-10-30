import type { ReactNode } from "react";
import { DevicesTab } from "../DevicesTab";
import { SchedulesTab, UnitsTab } from "../Operations";
import { EmployeeDetailScreen, EmployeesScreen } from "./Employees";
import { RecordsTab } from "../TimeclockTab";
import { type Destination, useRouter } from "../lib/router";
import { useCompany } from "../lib/session";
import { MembersPanel } from "../screens";
import { Group, Screen } from "../ui/kit";
import { AccountScreen, BillingScreen, CompanyScreen, FiscalScreen, RulesScreen } from "./Admin";
import { AvailabilityScreen } from "./Availability";
import { ClosingDetailScreen, ClosingsScreen } from "./Closings";
import { PlatformScreen } from "./Platform";
import { MyDayScreen, MyRequestsScreen, MyTimesheetScreen } from "./Portal";
import { RequestsScreen } from "./Requests";
import { TimesheetScreen } from "./Timesheet";
import { TodayScreen } from "./Today";

/** Mapa de destinos para telas (como `.navigationDestination(for:)`). */
export function ScreenView({
  destination,
  refreshPending,
}: {
  destination: Destination;
  refreshPending: () => void;
}) {
  const router = useRouter();
  switch (destination.screen) {
    case "today":
      return <TodayScreen />;
    case "timesheet":
      return (
        <TimesheetScreen
          employeeId={destination.employeeId}
          from={destination.from}
          to={destination.to}
        />
      );
    case "requests":
      return <RequestsScreen onDecided={refreshPending} />;
    case "closings":
      return <ClosingsScreen />;
    case "closing":
      return <ClosingDetailScreen id={destination.id} />;
    case "availability":
      return <AvailabilityScreen />;
    case "records":
      return (
        <Legacy
          title="Registros de ponto"
          subtitle="Todos os registros feitos nos tablets. Só para consulta: o registro original não é alterado nem apagado."
          render={(c) => (
            <RecordsTab
              key={`${destination.screen === "records" ? destination.from : ""}:${destination.screen === "records" ? destination.to : ""}`}
              companyId={c}
              from={destination.screen === "records" ? destination.from : undefined}
              to={destination.screen === "records" ? destination.to : undefined}
              onPeriod={(from, to) =>
                router.replaceTop({
                  screen: "records",
                  employeeId: destination.screen === "records" ? destination.employeeId : undefined,
                  from: from || undefined,
                  to: to || undefined,
                })
              }
            />
          )}
        />
      );
    case "devices":
      return (
        <Legacy
          title="Tablets de ponto"
          render={(c, admin) => <DevicesTab companyId={c} canEdit={admin} />}
        />
      );
    case "employees":
      return <EmployeesScreen />;
    case "employee":
      return <EmployeeDetailScreen id={destination.id} />;
    case "structure":
      return (
        <Legacy
          title="Unidades e setores"
          render={(c, admin) => <UnitsTab companyId={c} canEdit={admin} />}
        />
      );
    case "schedules":
      return (
        <Legacy
          title="Horários de trabalho"
          subtitle="Um horário já usado não pode ser editado. Para mudar, crie um novo e defina a data a partir da qual ele vale."
          render={(c, admin) => <SchedulesTab companyId={c} canEdit={admin} />}
        />
      );
    case "rules":
      return <RulesScreen />;
    case "fiscal":
      return <FiscalScreen />;
    case "company":
      return <CompanyScreen />;
    case "members":
      return <MembersScreenView />;
    case "billing":
      return <BillingScreen />;
    case "account":
      return <AccountScreen />;
    case "my-day":
      return <MyDayScreen />;
    case "my-timesheet":
      return <MyTimesheetScreen />;
    case "my-requests":
      return <MyRequestsScreen />;
    case "platform":
      return <PlatformScreen />;
    default:
      return <TodayScreen />;
  }
}

/** Telas de cadastro existentes, vestidas pela casca nova. */
function Legacy({
  title,
  subtitle,
  render,
}: {
  title: string;
  subtitle?: string;
  render: (companyId: number, isAdmin: boolean) => ReactNode;
}) {
  const { companyId, isAdmin } = useCompany();
  return (
    <Screen title={title} subtitle={subtitle}>
      <Group padded>
        <div className="legacy">{render(companyId, isAdmin)}</div>
      </Group>
    </Screen>
  );
}

function MembersScreenView() {
  const { companyId, role } = useCompany();
  return (
    <Screen
      title="Acessos"
      subtitle="Convide pessoas e escolha o que cada uma pode fazer no sistema."
    >
      <Group padded>
        <div className="legacy">
          <MembersPanel companyId={companyId} myRole={role} />
        </div>
      </Group>
    </Screen>
  );
}
