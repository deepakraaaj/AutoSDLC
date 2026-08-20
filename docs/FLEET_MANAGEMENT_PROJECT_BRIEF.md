# Project: Fleet Management Platform

## Executive Summary
A web-based fleet management platform that gives operations teams a single place to track vehicle location and health, schedule and enforce preventive maintenance, assign drivers to vehicles and trips, and monitor fuel/mileage costs. Fleet Managers get real-time visibility into where every vehicle is and whether it's roadworthy; Drivers get a simple mobile-friendly way to log trips and report issues; Maintenance Coordinators get proactive alerts before a vehicle breaks down instead of finding out after.

---

## Problem Statement
Mid-size fleets (30-500 vehicles) today run on a mix of spreadsheets, paper logs, and disconnected point tools — one system for GPS tracking, another for maintenance records, a spreadsheet for fuel spend, and a shared inbox for drivers reporting issues. Nothing talks to anything else. Fleet Managers can't answer "which vehicles are overdue for service" or "what's our actual cost per mile" without hours of manual reconciliation across systems. Preventive maintenance gets missed because there's no single source of truth for mileage/engine-hours-based service intervals, leading to breakdowns, unplanned downtime, and costly emergency repairs. There's no reliable record of who was driving which vehicle when, which becomes a real problem during incident investigations or insurance claims.

---

## Goals
- Give Fleet Managers a single real-time dashboard of vehicle location, status, and health across the whole fleet
- Automate preventive maintenance scheduling based on mileage/engine-hours/time intervals, cutting unplanned breakdowns by 50%
- Establish a reliable driver-to-vehicle-to-trip audit trail for every trip taken
- Reduce fuel and maintenance cost per mile through better visibility and fewer emergency repairs
- Give Drivers a low-friction mobile flow to start/end trips and report vehicle issues in under 30 seconds

---

## Success Metrics
- **Unplanned breakdown rate**: 50% reduction within 2 quarters of full rollout
- **Maintenance compliance**: 95%+ of scheduled services completed within their due window (mileage or date, whichever first)
- **Fleet Manager dashboard load time**: under 2 seconds for a 500-vehicle fleet
- **Driver trip-log completion rate**: 90%+ of trips logged (start + end) without manual follow-up
- **Cost-per-mile visibility**: Fleet Manager can pull a per-vehicle and fleet-wide cost-per-mile report for any date range in under 10 seconds

---

## Target Users

### Fleet Manager (primary)
- **Who:** Operations lead responsible for overall fleet uptime, cost, and compliance across all vehicles.
- **Need:** A real-time map/list view of every vehicle's location and status, maintenance-due alerts, and cost reporting — without pulling data from three different tools.
- **Success:** Can see fleet-wide status at a glance each morning, never gets surprised by an overdue-and-broken-down vehicle, and can produce a cost report for leadership in minutes.

### Driver
- **Who:** Employee assigned to drive one or more fleet vehicles for deliveries, service calls, or transport.
- **Need:** A dead-simple way (ideally mobile) to see which vehicle they're assigned to, start/end a trip, log mileage, and flag a problem with the vehicle.
- **Success:** Trip logging takes under 30 seconds and doesn't get in the way of the actual job; reported issues get acknowledged, not lost.

### Maintenance Coordinator
- **Who:** Schedules and tracks service work, either with in-house mechanics or outside shops.
- **Need:** A prioritized queue of vehicles due (or overdue) for service, driven by mileage/engine-hours/time thresholds, plus a place to log completed work and parts/labor cost.
- **Success:** Never finds out a service was missed after the fact; can see service history per vehicle at a glance.

### Dispatcher
- **Who:** Assigns vehicles and drivers to trips/jobs day-to-day.
- **Need:** Visibility into which vehicles are available, in service, or out for maintenance, so they don't assign a vehicle that's overdue or already in use.
- **Success:** Can make an assignment in seconds without calling around to check vehicle status.

---

## MVP Scope

### Must-Have Features (In Scope)
- Vehicle registry: make/model/year/VIN, assigned driver(s), current status (active, in-maintenance, out-of-service)
- Live location tracking per vehicle (GPS ping ingestion) shown on a fleet map and per-vehicle detail view
- Preventive maintenance scheduling: mileage-, engine-hours-, and date-based service intervals per vehicle/vehicle-type, with due/overdue alerts
- Maintenance work order logging: service performed, date, mileage at service, cost, performed by (in-house/vendor)
- Driver trip logging: start/end trip, odometer readings, linked to a specific vehicle and driver
- Driver issue reporting: flag a vehicle problem with description and severity, visible to Maintenance Coordinator
- Fleet Manager dashboard: fleet-wide status counts, overdue maintenance list, recent issues, basic cost-per-mile report

### Nice-to-Have (Out of Scope / v2)
- Route optimization / turn-by-turn dispatch routing
- Fuel card integration for automatic fuel spend capture
- Predictive maintenance (failure prediction from telemetry trends, not just fixed intervals)
- Driver scorecards (harsh braking, speeding, idle time) from telemetry

### Explicitly Out of Scope
- Federal ELD (Electronic Logging Device) hours-of-service compliance — this is fleet ops, not DOT compliance, for MVP
- Autonomous/AI dispatch assignment
- In-vehicle hardware manufacturing or firmware — MVP assumes a third-party GPS/telemetry device already exists and pushes data via API

---

## Core User Journeys

### Journey 1: Driver Completes a Trip
**Actor:** Driver

1. Driver opens the app (mobile web) and sees their currently assigned vehicle
2. Taps "Start Trip", enters starting odometer reading (or confirms auto-detected value)
3. Drives to complete the job
4. Taps "End Trip", enters ending odometer reading
5. Optionally flags an issue noticed during the trip (e.g., "brakes feel soft")
6. Trip is logged with driver, vehicle, mileage, and timestamps; any flagged issue routes to the Maintenance Coordinator

### Journey 2: Preventive Maintenance Alert to Completion
**Actor:** System (alert) → Maintenance Coordinator (action)

1. System evaluates each vehicle's mileage/engine-hours/date against its configured service intervals nightly
2. A vehicle crossing a threshold (e.g., "due for oil change in 500 miles") appears in the Maintenance Coordinator's due/overdue queue
3. Coordinator schedules the service (in-house or vendor) and marks the vehicle "in-maintenance" if it needs to come off active duty
4. Once service is complete, Coordinator logs work performed, mileage at service, and cost
5. The vehicle's next-due threshold recalculates automatically from the new service date/mileage
6. Vehicle status returns to "active"

### Journey 3: Fleet Manager Reviews Morning Status
**Actor:** Fleet Manager

1. Opens dashboard, sees fleet-wide counts: active / in-maintenance / out-of-service / overdue-for-service
2. Reviews the overdue-maintenance list, sorted by how overdue each vehicle is
3. Reviews open driver-reported issues by severity
4. Pulls a cost-per-mile report for the past 30 days, filterable by vehicle or vehicle group
5. Drills into a specific vehicle's detail view to see full service history, trip history, and current location

---

## Functional Requirements

### Vehicle Registry
- Create/edit vehicle records: VIN, make, model, year, license plate, vehicle type/class, assigned driver(s)
- Vehicle status: Active, In-Maintenance, Out-of-Service, Retired
- Per-vehicle detail view combining location, status, service history, and trip history

### Location Tracking
- Ingest GPS location pings per vehicle from a third-party telemetry provider via API
- Fleet-wide map view showing current vehicle positions
- Per-vehicle location history for a configurable lookback window (MVP: 30 days)

### Maintenance Scheduling
- Configure service intervals by vehicle type or individual vehicle: mileage-based, engine-hours-based, and/or calendar-based (whichever comes first)
- Automated nightly evaluation producing a due/overdue queue, ranked by urgency
- Work order logging: service type, date performed, mileage/hours at service, cost (parts + labor), performed by
- Next-due recalculation on work order completion

### Driver Trip Logging
- Start/end trip with odometer capture (manual entry, MVP; auto-capture from telemetry is v2)
- Trip history per driver and per vehicle
- Issue reporting attached to a trip or vehicle, with severity (low/medium/high) and free-text description

### Fleet Manager Dashboard & Reporting
- Fleet-wide status summary (counts by status)
- Overdue/due-soon maintenance list
- Open issues list by severity
- Cost-per-mile report: fuel + maintenance cost divided by miles driven, per vehicle and fleet-wide, filterable by date range

---

## Business Rules & Constraints
- A vehicle marked "In-Maintenance" or "Out-of-Service" cannot be assigned to a new trip
- Maintenance due dates are always calculated from whichever threshold (mileage/hours/date) is soonest, not an average
- A trip cannot be started without an assigned driver and an active vehicle
- Driver-reported issues with severity "high" must generate an immediate notification to the Maintenance Coordinator, not just appear in a queue
- Completed work orders are immutable once logged (corrections require a new entry, not an edit) to preserve service history integrity

---

## Non-Functional Requirements

### Performance
- Fleet map/dashboard load: under 2 seconds for up to 500 vehicles
- Location ping ingestion: support at least 1 ping/vehicle/minute across the full fleet without lag in the map view
- Cost-per-mile report generation: under 10 seconds for a 12-month date range

### Security & Compliance
- All data encrypted in transit (HTTPS) and at rest
- Role-based access: Drivers see only their own assignments/trips; Fleet Managers and Maintenance Coordinators have fleet-wide visibility scoped to their organization
- Audit log of maintenance record changes and status changes (who, what, when)

### Platform & Availability
- Fleet Manager/Coordinator/Dispatcher experience: responsive web app (Chrome, Firefox, Safari, latest 2 versions)
- Driver experience: mobile-responsive web (no native app required for MVP)
- 99.5% uptime target for the dashboard and trip-logging flows

### Data & Integrations
- Ingest location telemetry from a third-party GPS provider via REST API or webhook
- Export cost/maintenance reports as CSV
- Connect to company identity system (SSO) for login, if available — email/password acceptable fallback for MVP

---

## Data Entities

### Vehicle
- **ID**: Unique identifier (VIN)
- **Fields**: make, model, year, license_plate, vehicle_type, status, assigned_driver_ids, current_mileage, current_engine_hours
- **States**: Active, In-Maintenance, Out-of-Service, Retired
- **Owner**: Fleet Manager (creation), system (status/mileage updates)

### Driver
- **ID**: Unique identifier
- **Fields**: name, contact_info, license_number, assigned_vehicle_ids, status (active/inactive)
- **Owner**: Fleet Manager

### Trip
- **ID**: Unique identifier
- **Fields**: vehicle_id, driver_id, start_time, end_time, start_odometer, end_odometer, linked_issue_ids
- **States**: In-Progress, Completed
- **Owner**: Driver (creation via start/end actions)

### Maintenance Schedule
- **ID**: Unique identifier
- **Fields**: vehicle_id (or vehicle_type), service_type, interval_miles, interval_hours, interval_days, last_service_date, last_service_mileage, next_due_estimate
- **Owner**: Maintenance Coordinator (configuration), system (due-date calculation)

### Work Order
- **ID**: Unique identifier
- **Fields**: vehicle_id, service_type, performed_at, mileage_at_service, cost, performed_by, notes
- **States**: Scheduled, In-Progress, Completed
- **Owner**: Maintenance Coordinator

### Issue Report
- **ID**: Unique identifier
- **Fields**: vehicle_id, reported_by (driver_id), severity, description, status, linked_trip_id
- **States**: Open, Acknowledged, Resolved
- **Owner**: Driver (creation), Maintenance Coordinator (resolution)

---

## External Integrations

### GPS/Telemetry Provider
- Pushes vehicle location pings (and ideally mileage/engine-hours) via API or webhook
- Assumed to already be installed in each vehicle — no in-vehicle hardware work in MVP scope

### SSO / Identity Provider
- Optional for MVP; if present, used for Fleet Manager/Coordinator/Dispatcher login
- Drivers may use a simpler login (email/PIN) suited to mobile use in the field

---

## Technology Preferences

### Frontend
- React + TypeScript
- Mobile-responsive layout (no separate native app for MVP)

### Backend
- FastAPI (Python)
- PostgreSQL for data (vehicles, drivers, trips, maintenance, work orders)
- Background job scheduler for nightly maintenance-due evaluation

### Infrastructure
- AWS (EC2/ECS for app, RDS for database)
- Docker containers
- GitHub Actions for CI/CD

---

## Phased Rollout

### Phase 1 (MVP, Month 1-2)
- Vehicle registry, location tracking, driver trip logging
- Maintenance scheduling and work order logging
- Fleet Manager dashboard (status + overdue maintenance)
- Target: Pilot with one depot/region (~30-50 vehicles)

### Phase 2 (Month 3)
- Cost-per-mile reporting and CSV export
- Driver issue reporting with severity-based alerting
- SSO integration

### Phase 3 (Month 4+)
- Route optimization / dispatch routing
- Fuel card integration
- Predictive maintenance from telemetry trends
- Driver scorecards

---

## Risks & Assumptions

### Risks
- **Telemetry provider data quality/reliability**: Mitigation — validate ping frequency and accuracy during pilot before fleet-wide rollout; design ingestion to tolerate gaps gracefully
- **Low driver adoption of trip logging**: Mitigation — keep the mobile flow to under 30 seconds and pilot with a small group first to catch friction early
- **Maintenance interval misconfiguration causing missed services**: Mitigation — ship with sensible default intervals per common vehicle type, editable but not blank by default

### Assumptions
- Each vehicle already has (or will have) a compatible third-party GPS/telemetry device installed before onboarding
- Drivers have access to a smartphone or tablet in-vehicle for trip logging
- Maintenance work (in-house or vendor) is logged after the fact by a Coordinator, not in real-time by the mechanic

---

## Dependencies & Constraints
- Telemetry provider API access/credentials needed before location tracking can go live
- Initial maintenance interval defaults must be defined (by vehicle type) before Phase 1 pilot
- Pilot depot/region must be selected and drivers onboarded before Phase 1 begins

---

## Open Questions
- [ ] Which GPS/telemetry provider(s) need to be supported at launch?
- [ ] Should engine-hours tracking be required for all vehicles, or only heavy equipment?
- [ ] Is a native mobile app needed post-MVP, or does mobile-responsive web suffice long-term?
- [ ] Who owns maintenance interval configuration day-to-day — Maintenance Coordinator, or Fleet Manager?
- [ ] What's the expected fleet size at full rollout, for infrastructure sizing?

---

## Document Info
- **Created**: 2026-08-14
- **Owner**: Product Team
- **Status**: Ready for review
