import logging

import requests

from hockeygamebot import nhlapi
from hockeygamebot.helpers import utils
from hockeygamebot.models.gametype import GameType
from hockeygamebot.nhlapi import schedule


class Team(object):
    """Holds attributes related to a team - usually two created per game."""

    def __init__(
        self, team_id, team_name, short_name, tri_code, home_away, tv_channel, games, record, season
    ):
        self.team_id = team_id
        self.team_name = team_name
        self.short_name = short_name
        self.tri_code = tri_code
        self.home_away = home_away
        self.tv_channel = tv_channel
        self.games = games
        self.record = record
        self.season = season

        # Not passed in at object creation time
        # self.team_hashtag = team_hashtag(self.team_name)
        self.skaters = 5
        self.score = 0
        self.shots = 0
        self.power_play = False
        self._goalie_pulled = False
        self.preferred = False
        self.goals = []
        self.lines = {}
        self.overridelines = False
        self.nss_gamelog = None
        self.gameday_roster = {}

        # Break-up the record into wins, losses, ot
        self.wins = record["wins"]
        self.losses = record["losses"]
        try:
            self.ot = record["ot"]
        except KeyError:
            self.ot = None

        # Calculate Points
        self.points = (2 * self.wins) + self.ot

        # Send request for leading / trailing stats (via other API)
        try:
            api = utils.load_config()["endpoints"]["nhl_rpt_base"]
            lead_trail_stats_url = (
                "{}?isAggregate=false"
                "&reportType=basic&isGame=false&reportName=leadingtrailing"
                "&cayenneExp=seasonId={}%20and%20teamId={}".format(api, self.season, self.team_id)
            )
            logging.info("Getting leading / trailing stats for %s via NHL API.", self.short_name)
            lead_trail_stats = nhlapi.api.nhl_api(lead_trail_stats_url).json()
            lead_trail_stats = lead_trail_stats["data"][0]
            self.lead_trail_lead1P = "{}-{}-{}".format(
                lead_trail_stats["winsAfterLead1p"],
                lead_trail_stats["lossAfterLead1p"],
                lead_trail_stats["otLossAfterLead1p"],
            )
            self.lead_trail_lead2P = "{}-{}-{}".format(
                lead_trail_stats["winsAfterLead2p"],
                lead_trail_stats["lossAfterLead2p"],
                lead_trail_stats["otLossAfterLead2p"],
            )
            self.lead_trail_trail1P = "{}-{}-{}".format(
                lead_trail_stats["winsAfterTrail1p"],
                lead_trail_stats["lossAfterTrail1p"],
                lead_trail_stats["otLossAfterTrail1p"],
            )
            self.lead_trail_trail2P = "{}-{}-{}".format(
                lead_trail_stats["winsAfterTrail2p"],
                lead_trail_stats["lossAfterTrail2p"],
                lead_trail_stats["otLossAfterTrail2p"],
            )
        except (IndexError, KeyError) as e:
            # Stats not available (for this team or page timeout)
            logging.warning("Error getting Lead / Trail Stats - %s", e)
            self.lead_trail_lead1P = "N/A-N/A-N/A"
            self.lead_trail_lead2P = "N/A-N/A-N/A"
            self.lead_trail_trail1P = "N/A-N/A-N/A"
            self.lead_trail_trail2P = "N/A-N/A-N/A"

        # Send request to get stats
        try:
            api = utils.load_config()["endpoints"]["nhl_endpoint"]
            stats_url = "{api}/teams/{team}/stats".format(api=api, team=self.team_id)
            logging.info("Getting team stats for %s via NHL API.", self.short_name)
            stats = nhlapi.api.nhl_api(stats_url).json()
            stats = stats["stats"]
            self.team_stats = stats[0]["splits"][0]["stat"]
            self.rank_stats = stats[1]["splits"][0]["stat"]
        except (IndexError, KeyError) as e:
            logging.warning("Error getting team stats - %s", e)
            self.team_stats = "N/A"
            self.rank_stats = "N/A"

        # Send request to get current roster
        try:
            api = utils.load_config()["endpoints"]["nhl_endpoint"]
            roster_url = "{api}/teams/{team}/roster".format(api=api, team=self.team_id)
            logging.info("Getting roster for %s via NHL API.", self.short_name)
            roster = nhlapi.api.nhl_api(roster_url).json()
            self.roster = roster["roster"]
        except (IndexError, KeyError) as e:
            logging.warning("Error getting team roster - %s", e)
            self.roster = "N/A"

        # If DEBUG, print all objects
        logging.debug("#" * 80)
        logging.debug("%s - Team Attributes", self.short_name)
        for k, v in vars(self).items():
            logging.debug("%s: %s", k, v)
        logging.debug("#" * 80)

    @classmethod
    def from_json(cls, resp, homeaway):
        broadcasts = nhlapi.schedule.get_broadcasts(resp)

        # Easier parsing of team related attributes
        team = resp["teams"][homeaway]["team"]

        # The following are not always a 'cherry-pick' from the dictionary
        channel = broadcasts.get(homeaway)
        record = resp["teams"][homeaway]["leagueRecord"]

        if resp["gameType"] in (GameType.PLAYOFFS, GameType.PREASEASON):
            games = record["wins"] + record["losses"]
        else:
            games = record["wins"] + record["losses"] + record["ot"]

        return Team(
            team_id=team["id"],
            team_name=team["name"],
            short_name=team["teamName"],
            tri_code=team["abbreviation"],
            home_away=homeaway,
            tv_channel=channel if channel is not None else "N/A",
            games=games,
            record=record,
            season=resp["season"],
        )

    @property
    def current_record(self):
        return f"{self.wins}-{self.losses}-{self.ot}"

    def get_new_points(self, outcome):
        """Takes a game outcome and returns the team's udpated points."""
        current_points = self.points
        if outcome == "win":
            current_points += 2
        elif outcome == "loss":
            current_points += 0
        elif outcome == "ot":
            current_points += 1

        return current_points

    def get_new_record(self, outcome):
        """Takes a game outcome and returns the team's udpated record."""
        logging.debug("%s Current Record - %s", self.short_name, self.current_record)
        logging.debug("Outcome - %s", outcome)
        if outcome == "win":
            self.wins += 1
        elif outcome == "loss":
            self.losses += 1
        elif outcome == "ot":
            self.ot += 1

        new_record = "{} - {} - {}".format(self.wins, self.losses, self.ot)
        logging.debug("New Record - %s", new_record)
        return new_record

    def get_new_playoff_series(self, outcome):
        """Takes a game outcome and returns the team's udpated record."""
        if outcome == "win":
            self.wins += 1
        elif outcome == "loss":
            self.losses += 1
        new_record = "({} - {})".format(self.wins, self.losses)
        return new_record

    def get_stat_and_rank(self, attr):
        """Returns a teams statistic and rank in the NHL.

        Args:
            attr (str): Stat to retrieve (gamesPlayed, wins, losses, ot, pts, ptPctg, goalsPerGame,
                        goalsAgainstPerGame, evGGARatio, powerPlayPercentage, powerPlayGoals,
                        powerPlayGoalsAgainst, powerPlayOpportunities, penaltyKillPercentage,
                        shotsPerGame, shotsAllowed, winScoreFirst, winOppScoreFirst, winLeadFirstPer,
                        winLeadSecondPer, winOutshootOpp, winOutshotByOpp, faceOffsTaken, faceOffsWon,
                        faceOffsLost, faceOffWinPercentage, shootingPctg, savePctg)

        Returns:
            tuple: 0 - Stat, 1 - NHL Rank
        """
        stat = self.team_stats[attr]
        rank = self.rank_stats[attr]
        return stat, rank

    @property
    def roster_dict_by_name(self):
        roster_dict = {}
        for player in self.roster:
            person = player.get("person")
            id = person.get("id")
            name = person.get("fullName")
            number = player.get("jerseyNumber")
            roster_dict[name] = {}
            roster_dict[name]["id"] = id
            roster_dict[name]["jerseyNumber"] = number
        return roster_dict

    @property
    def roster_dict_by_number(self):
        roster_dict = {}
        for player in self.roster:
            person = player.get("person")
            id = person.get("id")
            name = person.get("fullName")
            number = player.get("jerseyNumber")
            roster_dict[number] = {}
            roster_dict[number]["id"] = id
            roster_dict[number]["name"] = name
        return roster_dict

    @property
    def gameday_roster_by_name(self):
        roster_dict = {}
        for id, player in self.gameday_roster.items():
            full_name = player.get("fullName")
            first_name = player.get("firstName")
            last_name = player.get("lastName")
            number = player.get("primaryNumber")
            roster_dict[full_name] = {}
            roster_dict[full_name]["id"] = id.replace("ID", "")
            roster_dict[full_name]["number"] = number
            roster_dict[full_name]["first_name"] = first_name
            roster_dict[full_name]["last_name"] = last_name
        return roster_dict

    @property
    def gameday_roster_by_number(self):
        roster_dict = {}
        for id, player in self.gameday_roster.items():
            full_name = player.get("fullName")
            first_name = player.get("firstName")
            last_name = player.get("lastName")
            number = player.get("primaryNumber")
            roster_dict[number] = {}
            roster_dict[number]["id"] = id
            roster_dict[number]["name"] = full_name
            roster_dict[number]["first_name"] = first_name
            roster_dict[number]["last_name"] = last_name
        return roster_dict

    @property
    def goalie_pulled(self):
        """Returns the goalie_pulled attribute of a team."""
        return self._goalie_pulled

    @goalie_pulled.setter
    def goalie_pulled(self, new_value):
        """Allows the goalie_pulled attribute to be set externally and checks for changes."""
        old_value = self.goalie_pulled
        self._goalie_pulled = new_value
        return bool(new_value is True and old_value is False)

    def goalie_pulled_setter(self, new_value):
        """Allows the goalie_pulled attribute to be set externally and checks for changes."""
        old_value = self.goalie_pulled
        self._goalie_pulled = new_value
        return bool(new_value is True and old_value is False)
