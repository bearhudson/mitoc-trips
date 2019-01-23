# -*- coding: utf-8 -*-
# Generated by Django 1.11.17 on 2019-01-23 03:44
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ws', '0014_trip_markdown_description'),
    ]

    operations = [
        migrations.CreateModel(
            name='LotteryAdjustment',
            fields=[
                ('id', models.AutoField(
                    auto_created=True,
                    primary_key=True,
                    serialize=False,
                    verbose_name='ID'
                )),
                ('adjustment', models.IntegerField()),
                ('time_created', models.DateTimeField(
                    auto_now_add=True
                )),
                ('expires', models.DateTimeField(
                    help_text='Time at which this override should no longer apply'
                )),
                ('creator', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='adjustments_made',
                    to='ws.Participant'
                )),
                ('participant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='adjustments_received',
                    to='ws.Participant'
                )),
            ],
        ),
    ]
