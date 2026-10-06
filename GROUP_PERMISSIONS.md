# Group Permissions Report (Section 3.4)

The platform currently relies on **Boolean role flags and logic barriers** (`is_staff`, `is_superuser`, and the custom `PartnerApprovalMiddleware`) rather than fine-grained row-level group permissions for access control. 

## 1. Admins (Staff/Superusers)
- **Access Level:** Granted visibility to everything. 
- **Mechanism:** Bypassed by `PartnerApprovalMiddleware` and granted access via boolean checks in the views (e.g., `user_passes_test(lambda u: u.is_staff)` or `request.user.is_staff`).

## 2. Approved Partners
- **Access Level:** Isolated strictly to their own data.
- **Mechanism:** Managed by `PartnerApprovalMiddleware`. Access is isolated using `get_partner_profile(request.user)` and QuerySet filters restricting them to their own leads, tickets, and orders. `user_can_access_object` helper ensures they cannot view or modify other partners' objects.

## 3. Unapproved Partners
- **Access Level:** Blocked from all state-changing activities.
- **Mechanism:** Intercepted by `PartnerApprovalMiddleware` which redirects them to an `approval_pending` view until a staff member approves them.

## 4. Django Groups
- **Access Level:** Not strictly required to enforce the Phase 0 business logic (as we isolated via ownership queries).
- **Mechanism:** Supported via `UserForm` for native admin-panel use. If groups are created (e.g. "Support Staff", "Managers"), they can be assigned to users, but the current views rely primarily on the `is_staff` flag.
