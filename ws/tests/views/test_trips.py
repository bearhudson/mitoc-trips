import re
from datetime import date

from bs4 import BeautifulSoup
from django.test import Client
from freezegun import freeze_time

import ws.utils.perms as perm_utils
from ws import enums, models
from ws.tests import TestCase, factories, strip_whitespace


class Helpers:
    client: Client

    @staticmethod
    def _form_data(form):
        for elem in form.find_all('textarea'):
            yield elem['name'], elem.text

        for elem in form.find_all('input'):
            yield elem['name'], elem.get('value', '')

        for select in form.find_all('select'):
            selection = select.find('option', selected=True)
            value = selection['value'] if selection else ''
            yield select['name'], value

    def _get(self, url: str):
        response = self.client.get(url)
        assert response.status_code == 200
        soup = BeautifulSoup(response.content, 'html.parser')
        return response, soup

    @staticmethod
    def _expect_title(soup, expected):
        title = strip_whitespace(soup.title.string)
        assert title == f'{expected} | MITOC Trips'

    @staticmethod
    def _expect_past_trips(response, expected_trip_pks):
        assert expected_trip_pks == [trip.pk for trip in response.context['past_trips']]

    @staticmethod
    def _expect_current_trips(response, expected_trip_pks):
        assert [
            trip.pk for trip in response.context['current_trips']
        ] == expected_trip_pks

    @staticmethod
    def _expect_upcoming_header(soup, expected_text):
        """Expect a text label on the header, plus the subscribe+digest buttons."""
        header = soup.body.find('h3')
        header_text = strip_whitespace(header.get_text())
        # There is an RSS button and a weekly email digest button included in the header
        assert header_text == f'{expected_text} RSS Weekly digest'

    @staticmethod
    def _expect_link_for_date(soup, datestring):
        link = soup.find('a', href=f'/trips/?after={datestring}')
        assert link.get_text(strip=True) == 'Previous trips'


@freeze_time("2019-02-15 12:25:00 EST")
class UpcomingTripsViewTest(TestCase, Helpers):
    def test_upcoming_trips_without_filter(self):
        """With no default filter, we only show upcoming trips."""
        response, soup = self._get('/trips/')
        # We don't bother rendering any past trips
        self.assertNotIn('past_trips', response.context)
        self._expect_title(soup, 'Upcoming trips')
        # We just say 'Upcoming trips' (no mention of date)
        self._expect_upcoming_header(soup, 'Upcoming trips')

    def test_invalid_filter(self):
        """When an invalid date is passed, we just ignore it."""
        # Make two trips that are in the future, but before the requested cutoff
        factories.TripFactory.create(trip_date='2019-02-28')
        factories.TripFactory.create(trip_date='2019-02-27')

        # Ask for upcoming trips after an invalid future date
        response, soup = self._get('/trips/?after=2019-02-31')

        # We warn the user that this date was invalid.
        warning = soup.find(class_='alert alert-danger')
        self.assertTrue(response.context['date_invalid'])
        self.assertIn('Invalid date', warning.get_text())

        # However, we still return results (behaving as if no date filter was given)
        # We don't include past trips, though, since the `after` cutoff was invalid
        # (We only show upcoming trips)
        self._expect_title(soup, 'Upcoming trips')
        self.assertNotIn('past_trips', response.context)
        # We use today's date for the 'previous trips' link
        self._expect_link_for_date(soup, '2018-02-15')

    def test_trips_with_filter(self):
        """We support filtering the responded list of trips."""
        # Make a very old trip that will not be in our filter
        factories.TripFactory.create(trip_date='2016-12-23')

        # Make an older trip, that takes place after our query
        expected_trip = factories.TripFactory.create(trip_date='2017-11-21')

        # Filter based on a date in the past
        response, soup = self._get('/trips/?after=2017-11-15')
        self.assertFalse(response.context['date_invalid'])

        # Observe that we have an 'Upcoming trips' section, plus a section for past trips
        self._expect_upcoming_header(soup, 'Upcoming trips')
        self._expect_title(soup, 'Trips after 2017-11-15')
        self._expect_past_trips(response, [expected_trip.pk])
        self._expect_link_for_date(soup, '2016-11-15')

    def test_upcoming_trips_can_be_filtered(self):
        """If supplying an 'after' date in the future, that still permits filtering!"""
        _next_week = factories.TripFactory.create(trip_date='2019-02-22')
        next_month = factories.TripFactory.create(trip_date='2019-03-22')
        response, soup = self._get('/trips/?after=2019-03-15')
        self._expect_link_for_date(soup, '2018-03-15')

        # We remove the RSS + email buttons
        header = soup.body.find('h3')
        self.assertEqual(strip_whitespace(header.text), 'Trips after Mar 15, 2019')

        # The trip next month is included, but not next week (since we're filtering ahead)
        self._expect_current_trips(response, [next_month.pk])


@freeze_time("2019-02-15 12:25:00 EST")
class AllTripsViewTest(TestCase, Helpers):
    def test_all_trips_with_no_past(self):
        """Even with no past trips, we still display 'All trips'"""
        response, soup = self._get('/trips/all/')
        self.assertFalse(response.context['past_trips'])
        self._expect_title(soup, 'All trips')

    def test_all_trips_with_past_trips(self):
        """Test the usual case - 'all trips' segmenting past & upcoming trips."""
        next_week = factories.TripFactory.create(trip_date='2019-02-22')
        last_month = factories.TripFactory.create(trip_date='2019-01-15')
        years_ago = factories.TripFactory.create(trip_date='2010-11-15')
        response, soup = self._get('/trips/all/')
        self._expect_title(soup, 'All trips')
        self._expect_current_trips(response, [next_week.pk])
        self._expect_past_trips(response, [last_month.pk, years_ago.pk])

    def test_all_trips_with_filter(self):
        """We support filtering trips even on the 'all' page.

        The default interaction with filtering trips should instead just use
        the `/trips/` URL, but this test demonstrates that filtering works on
        the 'all' page too.
        """
        # Make a very old trip that will not be in our filter
        factories.TripFactory.create(trip_date='2016-12-23')

        # Make an older trip, that takes place after our query
        expected_trip = factories.TripFactory.create(trip_date='2017-11-21')
        response, soup = self._get('/trips/all/?after=2017-11-15')
        self._expect_title(soup, 'Trips after 2017-11-15')
        self._expect_past_trips(response, [expected_trip.pk])
        self._expect_link_for_date(soup, '2016-11-15')


class CreateTripViewTest(TestCase, Helpers):
    @freeze_time("2019-12-15 12:25:00 EST")
    def test_superuser_can_create_any_program(self):
        """Even though it's not IAP, the superuser can make any trip type."""
        user = factories.UserFactory.create(is_superuser=True)
        factories.ParticipantFactory.create(user_id=user.pk)
        self.client.force_login(user)
        _resp, soup = self._get('/trips/create/')
        options = soup.find('select', attrs={'name': 'program'}).find_all('option')
        self.assertCountEqual(
            [opt['value'] for opt in options],
            [program.value for program in enums.Program],
        )

    @freeze_time("2019-12-15 12:25:00 EST")
    def test_winter_school_not_available_outside_iap(self):
        """Normal trip leaders can only make normal winter trips outside IAP."""
        leader = factories.ParticipantFactory.create()
        factories.LeaderRatingFactory.create(
            participant=leader, activity=models.LeaderRating.WINTER_SCHOOL
        )
        self.client.force_login(leader.user)
        _resp, soup = self._get('/trips/create/')
        options = soup.find('select', attrs={'name': 'program'}).find_all('option')
        programs = [opt['value'] for opt in options]
        self.assertIn(enums.Program.WINTER_NON_IAP.value, programs)
        self.assertNotIn(enums.Program.WINTER_SCHOOL.value, programs)

    def test_creation(self):
        """End-to-end test of form submission on creating a new trip.

        This is something of an integration test. Dealing with forms
        in this way is a bit of a hassle, but this ensures that we're handling
        everything properly.

        More specific behavior testing should be done at the form level.
        """
        user = factories.UserFactory.create()
        self.client.force_login(user)
        trip_leader = factories.ParticipantFactory.create(user=user)
        factories.LeaderRatingFactory.create(
            participant=trip_leader, activity=models.LeaderRating.BIKING
        )
        _resp, soup = self._get('/trips/create/')
        form = soup.find('form')
        form_data = dict(self._form_data(form))

        # We have the selections pre-populated too.
        self.assertEqual(form_data['program'], enums.Program.BIKING.value)
        self.assertEqual(form_data['algorithm'], 'lottery')

        # Fill in the form with some blank, but required values (accept the other defaults)
        form_data.update(
            {
                'name': 'My Great Trip',
                'trip_type': enums.TripType.MOUNTAIN_BIKING.value,
                'difficulty_rating': 'Intermediate',
                'description': "Let's go hiking!",
            }
        )
        self.assertEqual(form['action'], '.')

        # Upon form submission, we're redirected to the new trip's page!
        resp = self.client.post('/trips/create/', form_data, follow=False)
        self.assertEqual(resp.status_code, 302)
        new_trip_url = re.compile(r'^/trips/(\d+)/$')
        self.assertRegex(resp.url, new_trip_url)
        match = new_trip_url.match(resp.url)
        assert match is not None
        trip_pk = int(match.group(1))

        trip = models.Trip.objects.get(pk=trip_pk)
        self.assertEqual(trip.creator, trip_leader)
        self.assertEqual(trip.name, 'My Great Trip')


class EditTripViewTest(TestCase, Helpers):
    def test_superusers_may_edit_trip_without_required_activity(self):
        admin = factories.UserFactory.create(is_superuser=True)
        self.client.force_login(admin)

        trip = factories.TripFactory.create(program=enums.Program.SERVICE.value)
        self.assertIsNone(trip.required_activity_enum())

        _edit_resp, soup = self._get(f'/trips/{trip.pk}/edit/')
        self.assertTrue(soup.find('form'))

    def test_leaders_cannot_edit_other_leaders_trip(self):
        leader = factories.ParticipantFactory.create()
        factories.LeaderRatingFactory.create(
            participant=leader, activity=models.LeaderRating.CLIMBING
        )
        self.client.force_login(leader.user)

        trip = factories.TripFactory.create(
            name="Rad Trip", program=enums.Program.CLIMBING.value
        )

        _edit_resp, soup = self._get(f'/trips/{trip.pk}/edit/')
        self.assertTrue(soup.find('h2', text='Must be a leader to administrate trip'))
        self.assertFalse(soup.find('form'))

    def test_editing(self):
        user = factories.UserFactory.create(email='leader@example.com')
        self.client.force_login(user)
        trip_creator = factories.ParticipantFactory.create(user=user)
        factories.LeaderRatingFactory.create(
            participant=trip_creator, activity=models.LeaderRating.WINTER_SCHOOL
        )
        trip = factories.TripFactory.create(
            creator=trip_creator, program=enums.Program.WINTER_SCHOOL.value
        )
        trip.leaders.add(trip_creator)

        # Add an old leader to this trip, to demonstrate that editing & submitting is allowed
        old_leader = factories.ParticipantFactory.create()
        factories.LeaderRatingFactory.create(
            participant=old_leader,
            activity=models.LeaderRating.WINTER_SCHOOL,
            active=False,
        )
        trip.leaders.add(old_leader)

        _edit_resp, soup = self._get(f'/trips/{trip.pk}/edit/')
        form = soup.find('form')
        form_data = dict(self._form_data(form))

        # We supply the two leaders via an Angular directive
        # (Angular will be used to populate the `leaders` input, so manually populate here)
        self.assertEqual(
            soup.find('leader-select')['leader-ids'],
            f'[{trip_creator.pk}, {old_leader.pk}]',
        )
        form_data['leaders'] = [trip_creator.pk, old_leader.pk]

        # We have the selections pre-populated with existing data
        self.assertEqual(form_data['program'], enums.Program.WINTER_SCHOOL.value)
        self.assertEqual(form_data['algorithm'], 'lottery')

        # Make some updates to the trip!
        form_data.update({'name': 'An old WS trip'})
        self.assertEqual(form['action'], '.')

        # Upon form submission, we're redirected to the new trip's page!
        resp = self.client.post(f'/trips/{trip.pk}/edit/', form_data, follow=False)
        self.assertEqual(resp.status_code, 302)

        trip = models.Trip.objects.get(pk=trip.pk)
        self.assertEqual(trip.creator, trip_creator)
        self.assertCountEqual(trip.leaders.all(), [old_leader, trip_creator])
        self.assertEqual(trip.name, 'An old WS trip')

        # To support any legacy behavior still around, we set activity.
        self.assertEqual(trip.activity, 'winter_school')

    @freeze_time("2019-02-15 12:25:00 EST")
    def test_update_rescinds_approval(self):
        leader = factories.ParticipantFactory.create()
        self.client.force_login(leader.user)
        factories.LeaderRatingFactory.create(
            participant=leader, activity=enums.Activity.CLIMBING.value
        )
        trip = factories.TripFactory.create(
            creator=leader,
            program=enums.Program.CLIMBING.value,
            trip_date=date(2019, 3, 2),
            chair_approved=True,
        )

        edit_resp, soup = self._get(f'/trips/{trip.pk}/edit/')
        self.assertTrue(edit_resp.context['update_rescinds_approval'])

        form = soup.find('form')
        form_data = dict(self._form_data(form))

        self.assertEqual(
            strip_whitespace(soup.find(class_='alert-warning').text),
            'This trip has been approved by the activity chair. '
            'Making any changes will rescind this approval.',
        )

        # Upon form submission, we're redirected to the new trip's page!
        resp = self.client.post(f'/trips/{trip.pk}/edit/', form_data, follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, f'/trips/{trip.pk}/')

        # We can see that chair approval is now removed.
        trip = models.Trip.objects.get(pk=trip.pk)
        self.assertFalse(trip.chair_approved)


class ApproveTripsViewTest(TestCase):
    def setUp(self):
        self.user = factories.UserFactory.create()
        self.client.force_login(self.user)

    @staticmethod
    def _make_climbing_trip(chair_approved=False, **kwargs):
        return factories.TripFactory.create(
            program=enums.Program.CLIMBING.value,
            activity=enums.Activity.CLIMBING.value,
            chair_approved=chair_approved,
            **kwargs,
        )

    def test_unauthenticated(self):
        self.client.logout()
        response = self.client.get('/climbing/trips/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/accounts/login/?next=/climbing/trips/')

    def test_not_an_activity_chair(self):
        response = self.client.get('/climbing/trips/')
        self.assertEqual(response.status_code, 403)

    def test_bad_activity(self):
        response = self.client.get('/snowmobiling/trips/')
        self.assertEqual(response.status_code, 404)

    def test_no_trips_found(self):
        perm_utils.make_chair(self.user, enums.Activity.CLIMBING)
        response = self.client.get('/climbing/trips/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['trips_needing_approval'], [])
        self.assertIsNone(response.context['first_unapproved_trip'])

    def test_all_trips_approved(self):
        self._make_climbing_trip(chair_approved=True)
        self._make_climbing_trip(chair_approved=True)
        perm_utils.make_chair(self.user, enums.Activity.CLIMBING)
        response = self.client.get('/climbing/trips/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['trips_needing_approval'], [])
        self.assertIsNone(response.context['first_unapproved_trip'])

    def test_chair(self):
        self._make_climbing_trip(chair_approved=True)
        unapproved = factories.TripFactory.create(
            program=enums.Program.SCHOOL_OF_ROCK.value,
            activity=enums.Activity.CLIMBING.value,
            chair_approved=False,
        )
        perm_utils.make_chair(self.user, enums.Activity.CLIMBING)
        response = self.client.get('/climbing/trips/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['first_unapproved_trip'], unapproved)

    @freeze_time("2019-07-05 12:25:00 EST")
    def test_past_unapproved_trips_ignored(self):
        """We only prompt chairs to look at trips which are upcoming & unapproved."""
        # Unapproved, but it's in the past!
        self._make_climbing_trip(trip_date=date(2019, 7, 4))

        perm_utils.make_chair(self.user, enums.Activity.CLIMBING)
        response = self.client.get('/climbing/trips/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['first_unapproved_trip'])

        # Make some future trips now - these trips will be ranked by date/itinerary!
        fri = self._make_climbing_trip(trip_date=date(2019, 7, 5))
        sun = self._make_climbing_trip(trip_date=date(2019, 7, 7))
        sat = self._make_climbing_trip(trip_date=date(2019, 7, 6))

        context = self.client.get('/climbing/trips/').context
        self.assertEqual(context['trips_needing_approval'], [fri, sat, sun])
        self.assertEqual(context['first_unapproved_trip'], fri)

    @freeze_time("2019-07-05 12:25:00 EST")
    def test_trips_with_itinerary_first(self):
        """Trips that have an itinerary are first in the approval flow."""
        perm_utils.make_chair(self.user, enums.Activity.CLIMBING)

        sat_with_info = self._make_climbing_trip(
            trip_date=date(2019, 7, 6),
            info=factories.TripInfoFactory.create(),
        )
        sat_without_info = self._make_climbing_trip(
            trip_date=date(2019, 7, 6), info=None
        )
        sun_with_info = self._make_climbing_trip(
            trip_date=date(2019, 7, 7),
            info=factories.TripInfoFactory.create(),
        )
        sun_without_info = self._make_climbing_trip(
            trip_date=date(2019, 7, 7), info=None
        )

        context = self.client.get('/climbing/trips/').context
        self.assertEqual(
            context['trips_needing_approval'],
            [sat_with_info, sat_without_info, sun_with_info, sun_without_info],
        )
        self.assertEqual(context['first_unapproved_trip'], sat_with_info)

    @freeze_time("2019-07-05 12:25:00 EST")
    def test_trips_needing_itinerary(self):
        perm_utils.make_chair(self.user, enums.Activity.CLIMBING)

        sat_trip = self._make_climbing_trip(trip_date=date(2019, 7, 6))
        sun_trip = self._make_climbing_trip(trip_date=date(2019, 7, 7))
        sun_trip_info = self._make_climbing_trip(
            trip_date=date(2019, 7, 7), info=factories.TripInfoFactory.create()
        )

        dean = factories.ParticipantFactory.create(
            name="Dean Potter", email="dean@example.com"
        )
        sun_trip.leaders.add(dean)

        # Leaders with multiple trips aren't repeated
        lynn = factories.ParticipantFactory.create(
            name="Lynn Hill", email="lynn@example.com"
        )
        sat_trip.leaders.add(lynn)
        sun_trip.leaders.add(lynn)

        # This trip is a week away; itineraries aren't open yet
        next_sat_trip = self._make_climbing_trip(trip_date=date(2019, 7, 13))

        # Alex has no trips that need itinerary
        alex = factories.ParticipantFactory.create(
            name="Alex Puccio", email="alex@example.com"
        )
        sun_trip_info.leaders.add(alex)
        next_sat_trip.leaders.add(alex)

        context = self.client.get('/climbing/trips/').context
        # Leaders are sorted by name
        self.assertEqual(
            context['leader_emails_missing_itinerary'],
            '"Dean Potter" <dean@example.com>, "Lynn Hill" <lynn@example.com>',
        )
