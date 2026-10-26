# Copyright (c) 2026, one-fm and contributors
"""set_permissions upsert and named revoke_permissions in integrations/google_drive.py.

The Drive client is replaced by a small in-memory fake, so these tests check
which Drive calls are made (update vs create vs delete) without any network.
"""

import unittest
from unittest.mock import MagicMock

from one_bpmn.one_bpmn.integrations import google_drive as gd

FILE_ID = "file-1"

DOMAIN_READER = {"id": "p-domain", "type": "domain", "domain": "one-fm.com", "role": "reader"}
REQUESTER = {"id": "p-req", "type": "user", "emailAddress": "requester@one-fm.com", "role": "writer"}
OTHER_USER = {"id": "p-other", "type": "user", "emailAddress": "other@one-fm.com", "role": "writer"}
INHERITED_USER = {
	"id": "p-inh",
	"type": "user",
	"emailAddress": "drive.member@one-fm.com",
	"role": "writer",
	"permissionDetails": [{"inherited": True, "inheritedFrom": "drive-1"}],
}
MEMBER_WITH_DIRECT_GRANT = {
	"id": "p-mixed",
	"type": "user",
	"emailAddress": "member@one-fm.com",
	"role": "writer",
	"permissionDetails": [{"inherited": True, "inheritedFrom": "drive-1"}, {"inherited": False}],
}


def fake_service(permissions):
	"""A MagicMock Drive service whose permissions().list() returns ``permissions``."""
	service = MagicMock()
	perms = service.permissions.return_value
	perms.list.return_value.execute.return_value = {"permissions": [dict(p) for p in permissions]}
	perms.create.return_value.execute.return_value = {"id": "new"}
	perms.update.return_value.execute.return_value = {"id": "updated"}
	return service, perms


class TestSetPermissionsUpsert(unittest.TestCase):
	def test_existing_user_grant_changes_role_from_writer_to_reader(self):
		service, perms = fake_service([DOMAIN_READER, REQUESTER])

		results = gd.set_permissions(
			FILE_ID,
			[{"type": "user", "emailAddress": "Requester@one-fm.com", "role": "reader"}],
			service=service,
		)

		perms.update.assert_called_once()
		kwargs = perms.update.call_args.kwargs
		self.assertEqual(kwargs["fileId"], FILE_ID)
		self.assertEqual(kwargs["permissionId"], "p-req")
		self.assertEqual(kwargs["body"], {"role": "reader"})
		perms.create.assert_not_called()
		self.assertEqual(len(results), 1)

	def test_new_email_is_created(self):
		service, perms = fake_service([DOMAIN_READER, REQUESTER])
		grant = {"type": "user", "emailAddress": "new@one-fm.com", "role": "writer"}

		gd.set_permissions(FILE_ID, [grant], service=service)

		perms.create.assert_called_once()
		self.assertEqual(perms.create.call_args.kwargs["body"], grant)
		perms.update.assert_not_called()

	def test_domain_grant_is_created_without_listing(self):
		service, perms = fake_service([DOMAIN_READER])
		grant = {"type": "domain", "domain": "one-fm.com", "role": "reader"}

		gd.set_permissions(FILE_ID, [grant], service=service)

		perms.create.assert_called_once()
		self.assertEqual(perms.create.call_args.kwargs["body"], grant)
		perms.update.assert_not_called()
		perms.list.assert_not_called()

	def test_inherited_access_is_not_updated(self):
		service, perms = fake_service([INHERITED_USER])

		gd.set_permissions(
			FILE_ID,
			[{"type": "user", "emailAddress": "drive.member@one-fm.com", "role": "reader"}],
			service=service,
		)

		perms.update.assert_not_called()
		perms.create.assert_called_once()


class TestDirectGrantAlongsideInheritedAccess(unittest.TestCase):
	def test_upsert_changes_the_direct_grant_of_a_drive_member(self):
		service, perms = fake_service([DOMAIN_READER, MEMBER_WITH_DIRECT_GRANT])

		gd.set_permissions(
			FILE_ID,
			[{"type": "user", "emailAddress": "member@one-fm.com", "role": "reader"}],
			service=service,
		)

		perms.update.assert_called_once()
		self.assertEqual(perms.update.call_args.kwargs["permissionId"], "p-mixed")
		self.assertEqual(perms.update.call_args.kwargs["body"], {"role": "reader"})
		perms.create.assert_not_called()

	def test_named_revoke_removes_the_direct_grant_of_a_drive_member(self):
		service, perms = fake_service([DOMAIN_READER, MEMBER_WITH_DIRECT_GRANT, OTHER_USER])

		outcome = gd.revoke_permissions(
			FILE_ID, scope="user", email_address="member@one-fm.com", service=service
		)

		perms.delete.assert_called_once()
		self.assertEqual(perms.delete.call_args.kwargs["permissionId"], "p-mixed")
		self.assertEqual([p["id"] for p in outcome["removed"]], ["p-mixed"])
		self.assertEqual(outcome["skipped"], [])


class TestNamedRevoke(unittest.TestCase):
	def test_named_revoke_leaves_other_user_and_domain_grant(self):
		service, perms = fake_service([DOMAIN_READER, REQUESTER, OTHER_USER])

		outcome = gd.revoke_permissions(
			FILE_ID, scope="user", email_address="requester@one-fm.com", service=service
		)

		perms.delete.assert_called_once()
		self.assertEqual(perms.delete.call_args.kwargs["permissionId"], "p-req")
		self.assertEqual([p["id"] for p in outcome["removed"]], ["p-req"])
		self.assertEqual(outcome["skipped"], [])

	def test_inherited_grant_is_reported_skipped_and_never_deleted(self):
		service, perms = fake_service([DOMAIN_READER, OTHER_USER, INHERITED_USER])

		outcome = gd.revoke_permissions(
			FILE_ID, scope="user", email_address="drive.member@one-fm.com", service=service
		)

		perms.delete.assert_not_called()
		self.assertEqual(outcome["removed"], [])
		self.assertEqual(len(outcome["skipped"]), 1)
		self.assertEqual(outcome["skipped"][0]["id"], "p-inh")
		self.assertIn("inherited", outcome["skipped"][0]["reason"])

	def test_scope_all_still_removes_direct_grants_and_skips_inherited(self):
		service, perms = fake_service([DOMAIN_READER, REQUESTER, INHERITED_USER])

		outcome = gd.revoke_permissions(FILE_ID, scope="all", service=service)

		deleted = sorted(c.kwargs["permissionId"] for c in perms.delete.call_args_list)
		self.assertEqual(deleted, ["p-domain", "p-req"])
		self.assertEqual([p["id"] for p in outcome["skipped"]], ["p-inh"])
