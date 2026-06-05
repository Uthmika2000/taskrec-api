const userService = require('../services/userService');

function handleError(error, res, next) {
  if (error.statusCode) return res.status(error.statusCode).json({ success: false, message: error.message });
  next(error);
}

exports.getUsers = async (req, res, next) => {
  try {
    const users = await userService.getUsers(req.query);
    res.json({ success: true, data: users });
  } catch (error) { handleError(error, res, next); }
};

exports.getUser = async (req, res, next) => {
  try {
    const user = await userService.getUser(req.params.id);
    res.json({ success: true, data: user });
  } catch (error) { handleError(error, res, next); }
};

exports.updateSkills = async (req, res, next) => {
  try {
    const user = await userService.updateSkills(req.params.id, req.body.skillTags, req.user);
    res.json({ success: true, data: user });
  } catch (error) { handleError(error, res, next); }
};
