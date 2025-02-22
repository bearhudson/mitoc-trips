# Generated by Django 2.2.24 on 2021-09-28 18:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ws', '0037_denormalize_hibp_passwords'),
    ]

    operations = [
        migrations.AlterField(
            model_name='trip',
            name='allow_leader_signups',
            field=models.BooleanField(
                default=False,
                help_text='Leaders can add themselves directly to the list of trip leaders, even if trip is full or in lottery mode. Recommended for Circuses!',
            ),
        ),
        migrations.AlterField(
            model_name='trip',
            name='honor_participant_pairing',
            field=models.BooleanField(
                default=True,
                help_text='Try to place paired participants together on the trip (if both sign up).',
            ),
        ),
        migrations.AlterField(
            model_name='trip',
            name='membership_required',
            field=models.BooleanField(
                default=True,
                help_text='Require an active MITOC membership to participate (waivers are always required).',
            ),
        ),
    ]
