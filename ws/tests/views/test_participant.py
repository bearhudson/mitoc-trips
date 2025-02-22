import random
from datetime import date, datetime
from unittest import mock

import pytz
from bs4 import BeautifulSoup
from django.contrib.auth.models import Group
from freezegun import freeze_time

import ws.utils.perms as perm_utils
from ws import enums, models, tasks
from ws.tests import TestCase, factories, strip_whitespace
from ws.views.participant import logger


class LandingPageTests(TestCase):
    @freeze_time("2020-01-12 09:00:00 EST")
    def test_unauthenticated_rendering_enough_upcoming_trips(self):
        # Ten upcoming trips, with the most recent ones first
        ten_upcoming_trips = [
            factories.TripFactory.create(trip_date=date(2020, 1, 30 - i))
            for i in range(10)
        ]

        response = self.client.get('/')
        soup = BeautifulSoup(response.content, 'html.parser')
        lead_paragraph = soup.find('p', class_='lead')
        self.assertEqual(
            lead_paragraph.text,
            'Come hiking, climbing, skiing, paddling, biking, and surfing with the MIT Outing Club!',
        )

        # All trips are listed in reverse chronological order
        self.assertEqual(list(response.context['current_trips']), ten_upcoming_trips)
        # No recent trips are needed, since we have more than eight
        self.assertNotIn('recent_trips', response.context)

    @freeze_time("2020-01-12 09:00:00 EST")
    def test_unauthenticated_rendering_few_upcoming_trips(self):
        # Ten previous trips, with the most recent ones first
        ten_past_trips = [
            factories.TripFactory.create(trip_date=date(2019, 12, 30 - i))
            for i in range(1, 11)
        ]

        upcoming_trip1 = factories.TripFactory.create(trip_date=date(2020, 1, 15))
        upcoming_trip2 = factories.TripFactory.create(trip_date=date(2020, 1, 20))

        response = self.client.get('/')

        # Upcoming trips are listed in reverse chronological order
        self.assertEqual(
            list(response.context['current_trips']), [upcoming_trip2, upcoming_trip1]
        )
        # Recent trips are shown until we have 8 total
        self.assertEqual(list(response.context['recent_trips']), ten_past_trips[:6])


class ProfileViewTests(TestCase):
    def test_dated_affiliation_redirect(self):
        # Make a participant with a legacy affiliation
        participant = factories.ParticipantFactory.create(affiliation='S')
        self.client.force_login(participant.user)
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/profile/edit/')


@freeze_time("2020-01-12 09:00:00 EST")
class WimpDisplayInProfileViewTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = factories.UserFactory.create()
        self.participant = factories.ParticipantFactory.create(user_id=self.user.pk)
        self.client.force_login(self.user)

    @staticmethod
    def _create_wimp():
        wimp_par = factories.ParticipantFactory.create()
        Group.objects.get(name='WIMP').user_set.add(wimp_par.user_id)
        return wimp_par

    def test_admins_always_see_wimp(self):
        admin = factories.UserFactory.create(is_superuser=True)
        factories.ParticipantFactory.create(user_id=admin.pk)
        self.client.force_login(admin)
        wimp_par = self._create_wimp()

        resp = self.client.get('/')
        self.assertEqual(resp.context['wimp'], wimp_par)

    def test_participants_not_shown_wimp(self):
        # Upcoming WS trip exists
        factories.TripFactory.create(
            trip_date=date(2020, 1, 20), program=enums.Program.WINTER_SCHOOL.value
        )
        self._create_wimp()

        # Normal participants don't see the WIMP
        resp = self.client.get('/')
        self.assertIsNone(resp.context['wimp'])

    def test_no_wimp_shown_until_upcoming_ws_trips(self):
        # Trip exists from yesterday (it's currently during IAP too)
        factories.TripFactory.create(
            trip_date=date(2020, 1, 11), program=enums.Program.WINTER_SCHOOL.value
        )

        # Viewing participant is a WS leader
        factories.LeaderRatingFactory.create(
            participant=self.participant,
            activity=enums.Activity.WINTER_SCHOOL.value,
        )

        # We have an assigned WIMP
        wimp_par = self._create_wimp()

        # Because there are no upcoming WS trips, though - no WIMP is shown
        resp = self.client.get('/')
        self.assertIsNone(resp.context['wimp'])

        # If a trip is created today, we will then show the WIMP!
        factories.TripFactory.create(
            trip_date=date(2020, 1, 12), program=enums.Program.WINTER_SCHOOL.value
        )

        # Now, we show the WIMP because there are upcoming WS trips
        resp = self.client.get('/')
        self.assertEqual(resp.context['wimp'], wimp_par)

    def test_chairs_see_wimp_even_if_not_leaders(self):
        # WS trip exists today!
        factories.TripFactory.create(
            trip_date=date(2020, 1, 12), program=enums.Program.WINTER_SCHOOL.value
        )
        perm_utils.make_chair(self.user, enums.Activity.WINTER_SCHOOL)
        wimp_par = self._create_wimp()

        # There are upcoming WS trips, so the WS chairs should see the WIMP
        resp = self.client.get('/')
        self.assertEqual(resp.context['wimp'], wimp_par)


@freeze_time("2019-02-15 12:25:00 EST")
class EditProfileViewTests(TestCase):
    # 3 separate forms (does not include a car!)
    form_data = {
        # Participant
        'participant-name': 'New Participant',
        'participant-email': 'new.participant@example.com',
        'participant-cell_phone': '+1 800-555-0000',
        'participant-affiliation': 'NA',
        # Emergency information
        'einfo-allergies': 'N/A',
        'einfo-medications': 'N/A',
        'einfo-medical_history': 'Nothing relevant',
        # Emergency contact
        'econtact-name': 'Participant Sister',
        'econtact-email': 'sister@example.com',
        'econtact-cell_phone': '+1 800-555-1234',
        'econtact-relationship': 'Sister',
    }

    def setUp(self):
        super().setUp()
        self.user = factories.UserFactory.create()
        self.client.force_login(self.user)

    def _assert_form_data_saved(self, participant):
        """Assert that the given participant has data from `form_data`."""
        self.assertEqual(participant.name, 'New Participant')
        self.assertEqual(participant.email, 'new.participant@example.com')
        self.assertEqual(participant.affiliation, 'NA')
        self.assertEqual(participant.cell_phone.as_e164, '+18005550000')

        self.assertIsNone(participant.car)

        e_contact = participant.emergency_info.emergency_contact
        expected_contact = models.EmergencyContact(
            pk=e_contact.pk,
            name='Participant Sister',
            email='sister@example.com',
            cell_phone=mock.ANY,  # Tested below
            relationship='Sister',
        )

        self.assertEqual(
            participant.emergency_info,
            models.EmergencyInfo(
                pk=participant.emergency_info.pk,
                allergies='N/A',
                medications='N/A',
                medical_history='N/A',
                emergency_contact=expected_contact,
            ),
        )
        self.assertEqual(e_contact.cell_phone.as_e164, '+18005551234')

    def test_new_participant(self):
        response = self.client.get('/profile/edit/')
        soup = BeautifulSoup(response.content, 'html.parser')

        self.assertEqual(
            soup.find(class_='alert').get_text(strip=True),
            'Please complete this important safety information to finish the signup process.',
        )
        with mock.patch.object(tasks, 'update_participant_affiliation') as task_update:
            response = self.client.post('/profile/edit/', self.form_data, follow=False)

        # The save was successful, redirects home
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')

        participant = models.Participant.objects.get(
            email='new.participant@example.com'
        )

        self._assert_form_data_saved(participant)

        # We call an async task to update the affiliation for the participant
        task_update.delay.assert_called_with(participant.pk)

        # We then update the timestamps!
        now = datetime(2019, 2, 15, 17, 25, tzinfo=pytz.utc)
        self.assertEqual(participant.last_updated, now)
        # Since the participant modified their own profile, we save `profile_last_updated`
        self.assertEqual(participant.profile_last_updated, now)

    def test_existing_participant_with_problems(self):
        factories.ParticipantFactory.create(name='Cher', user_id=self.user.pk)

        response = self.client.get('/profile/edit/')
        soup = BeautifulSoup(response.content, 'html.parser')

        self.assertEqual(
            soup.find(class_='alert').get_text(strip=True),
            "Please supply your full legal name.",
        )


class ParticipantDetailViewTest(TestCase):
    def setUp(self):
        super().setUp()
        self.user = factories.UserFactory.create()
        self.client.force_login(self.user)

        self.participant = factories.ParticipantFactory.create()

    def test_non_authenticated_redirected(self):
        self.client.logout()
        response = self.client.get(f'/participants/{self.participant.pk}/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url, f'/accounts/login/?next=/participants/{self.participant.pk}/'
        )

    def test_non_participants_redirected(self):
        user = factories.UserFactory.create()
        self.client.force_login(user)
        response = self.client.get(f'/participants/{self.participant.pk}/')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url, f'/profile/edit/?next=/participants/{self.participant.pk}/'
        )

    def test_non_leaders_blocked(self):
        factories.ParticipantFactory.create(user_id=self.user.pk)
        response = self.client.get(f'/participants/{self.participant.pk}/')

        self.assertEqual(response.status_code, 403)

    def test_redirect_to_own_home(self):
        par = factories.ParticipantFactory.create(user_id=self.user.pk)
        response = self.client.get(f'/participants/{par.pk}/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')

    def test_leaders_can_view_others(self):
        par = factories.ParticipantFactory.create(user_id=self.user.pk)

        factories.FeedbackFactory.create(participant=self.participant)
        factories.FeedbackFactory.create(
            participant=self.participant,
            showed_up=False,
            comments='Slept through their alarm, did not answer phone calls',
        )

        # Any leader may view - it doesn't matter which activity!
        factories.LeaderRatingFactory.create(participant=par)
        self.assertTrue(perm_utils.is_leader(self.user))
        random.seed("Set seed, for predictable 'scrambling'")
        response = self.client.get(f'/participants/{self.participant.pk}/')
        self.assertEqual(response.status_code, 200)

        # When viewing, comments are initially scrambled
        soup = BeautifulSoup(response.content, 'html.parser')
        feedback = soup.find(id='feedback').find_next('table')
        self.assertEqual(
            strip_whitespace(feedback.find_next('td').text),
            'Flaked! oo srephh ,twihlien lnSd rmleartpagtsal choeanrudt',
        )

        # There's a button which enables us to view this feedback, unscrambled.
        reveal = soup.find(
            'a', href=f'/participants/{self.participant.pk}/?show_feedback=1'
        )
        self.assertTrue(reveal)
        with mock.patch.object(logger, 'info') as log_info:
            response = self.client.get(reveal.attrs['href'])
        log_info.assert_called_once_with(
            "%s (#%d) viewed feedback for %s (#%d)",
            par,
            par.pk,
            self.participant,
            self.participant.pk,
        )
        soup = BeautifulSoup(response.content, 'html.parser')
        feedback = soup.find(id='feedback').find_next('table')
        self.assertEqual(
            strip_whitespace(feedback.find_next('td').text),
            'Flaked! Slept through their alarm, did not answer phone calls',
        )
