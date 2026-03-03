# Login ID and Password Logic

This document explains how login IDs are formed in this project and what default passwords are set by seed logic.

## 1) How Login IDs are formed

## District users
- Pattern: `district_<district_code>`
- Source logic: `backend/app/services/bootstrap_service.py`
- Example:
  - district code `603` -> login ID `district_603`

## State users
- Pattern: `state_<state_code>`
- Source logic: `backend/app/services/bootstrap_service.py`
- Example:
  - state code `33` -> login ID `state_33`

## National user (single fixed ID)
- Fixed login ID: `national_admin`
- Source logic: `backend/app/services/bootstrap_service.py`

## Admin user (single fixed ID)
- Fixed login ID: `admin`
- Source logic: `backend/app/services/bootstrap_service.py`

So yes, by design there are many district/state IDs (code-based), but only one fixed national ID and one fixed admin ID from bootstrap.

## 2) Default passwords

## Bootstrap defaults (primary app bootstrap)
From `backend/app/services/bootstrap_service.py`:
- `district_<district_code>` -> password `district123`
- `state_<state_code>` -> password `state123`
- `national_admin` -> password `national123`
- `admin` -> password `admin123`

## E2E seed defaults (alternate test seeding path)
From `backend/e2e_seed_data.py`:
- `district_user` -> password `pw`
- `state_user` -> password `pw`
- `national_user` -> password `pw`
- `admin_user` -> password `pw`

This means the actual working credentials depend on which seed/bootstrap path was run for your current database.

## 3) Password storage rule
- Passwords are not stored as plain text.
- Hash function used: SHA-256
- Source: `backend/app/utils/hashing.py` (`hash_password(password)`)

## 4) Quick practical mapping for your current flow
For the standard bootstrap-style role IDs:
- District login: `district_<district_code>` + `district123`
- State login: `state_<state_code>` + `state123`
- National login: `national_admin` + `national123`
- Admin login: `admin` + `admin123`

For E2E/test-style IDs:
- `district_user` / `state_user` / `national_user` / `admin_user` all use `pw`

## 5) Notes about Login UI selectors
- The login request only sends `username` and `password` to `/auth/login`.
- Role/state/district dropdowns in UI are not sent in the login payload and do not override backend user role.
