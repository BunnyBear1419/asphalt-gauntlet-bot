# Racing Syndicate League Tournament Admin Guide

## Tournament setup

1. Open **Tournaments → Tournament Center** while signed into an authorized staff account.
2. Create the tournament with its name, description, bracket format, team size, entrant limit, registration window, and start/end times.
3. Choose the match-result workflow:
   - **Player Submission + Admin Verification** — players can report results; a tournament admin verifies them before the bracket advances.
   - **Admin Only** — only tournament staff can enter results; an approved admin result advances the bracket immediately. This is intended for closely supervised or streamed events.
4. For team events, choose **2v2, 3v3, or 4v4**. Clubs can provide the roster/lineup used for the event.

## Before the tournament

- Confirm the tournament admin role and announcement role are configured.
- Review accepted registrations and check-ins.
- Confirm team lineups are complete for team tournaments.
- Confirm the registration count meets the selected bracket requirements.
- Start the tournament once the roster is final. The start operation is protected against duplicate concurrent starts.

## During matches

### Admin Only

An authorized tournament admin enters the winner from the match controls. The result is recorded and the bracket advances immediately.

### Player Submission + Admin Verification

A player submits the result. It remains pending until tournament staff approves or rejects it. Approval advances the bracket; rejection returns the match to a playable state.

The same verification path handles winners/losers routing, round robin completion, double-elimination losers brackets, and the grand-final reset when required.

## Tournament media

Staff can upload official photos and videos directly to the tournament. Players can also submit media tied to that tournament.

- Staff submissions publish immediately.
- Player submissions enter **Pending Approval**.
- Staff can approve or reject pending media from the website.
- Authorized Discord tournament staff can use the persistent **Approve & Publish** / **Reject** controls.
- Only approved media is served to players and visitors.
- Uploaded media is size-bounded and served with private caching and content-type protection.

Use descriptive titles/captions so the completed tournament archive is easy to browse.

## After the tournament

Completed tournaments appear in **Results & Rankings** with:

- champion
- final standings
- verified match history
- published tournament media
- links back to the tournament and bracket

The player competitive profile also links completed tournament history back to the results archive.

## Operational checklist

- [ ] All matches are verified.
- [ ] Champion/final standings are recorded.
- [ ] Pending player media has been reviewed.
- [ ] Important official media has been uploaded.
- [ ] Tournament results page shows the completed event.
- [ ] Calendar/event records remain intact.
- [ ] No duplicate active registrations remain.

## Data maintenance

The production application uses MongoDB indexes for tournament action locks, active player/club registration uniqueness, tournament media lookup, and notification delivery. Do not manually remove tournament records or indexes from Atlas unless the application/data-maintenance procedure calls for it.

For abandoned or stale records, prefer an explicit staff/admin maintenance operation or a reviewed database cleanup rather than automatic deletion of competition history.